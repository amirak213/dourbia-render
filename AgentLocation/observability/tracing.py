from __future__ import annotations
import asyncio, dataclasses, json, logging, time
from typing import Optional
from uuid import uuid4
from core.config import settings
from core.infra import get_pool, record_to_dict

log = logging.getLogger("dourbia.observability")

@dataclasses.dataclass
class Span:
    span_id: str = dataclasses.field(default_factory=lambda: str(uuid4())[:8])
    name: str = ""
    start_ms: int = dataclasses.field(default_factory=lambda: int(time.time()*1000))
    end_ms: int = 0
    status: str = "running"
    metadata: dict = dataclasses.field(default_factory=dict)
    error: Optional[str] = None
    def finish(self, status="ok", error=None):
        self.end_ms=int(time.time()*1000); self.status=status; self.error=error
    @property
    def duration_ms(self): return (self.end_ms or int(time.time()*1000)) - self.start_ms
    def to_dict(self): d=dataclasses.asdict(self); d["duration_ms"]=self.duration_ms; return d

class AgentTrace:
    def __init__(self, session_id, user_message):
        self.trace_id=str(uuid4()); self.session_id=session_id; self.user_message=user_message
        self.spans=[]; self.start_ms=int(time.time()*1000); self.metadata={}
    def new_span(self, name, **meta) -> Span:
        s=Span(name=name, metadata=meta); self.spans.append(s); return s
    @property
    def total_ms(self): return int(time.time()*1000)-self.start_ms

_langfuse = None
def get_langfuse():
    global _langfuse
    if _langfuse is None and settings.langfuse_secret_key:
        try:
            from langfuse import Langfuse
            _langfuse = Langfuse(secret_key=settings.langfuse_secret_key,
                                  public_key=settings.langfuse_public_key, host=settings.langfuse_host)
            log.info("[OBS] Langfuse activé")
        except Exception as e: log.debug(f"[OBS] Langfuse : {e}")
    return _langfuse

async def persist_trace(session_id, trace_id, user_message, assistant_reply, intention,
                         tools_called, tool_errors, reflection_triggered, correction_applied,
                         guard_blocked, guard_score, tokens_used, latency_ms, model_used,
                         episodic_hits, error, spans):
    pool = await get_pool()
    try:
        await pool.execute("""
            INSERT INTO agent_traces (session_id,trace_id,user_message,assistant_reply,intention,
            tools_called,tool_errors,reflection_triggered,reflection_result,correction_applied,
            guard_blocked,guard_score,tokens_used,latency_ms,model_used,episodic_hits,error)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
        """, session_id, trace_id, user_message, assistant_reply, intention,
            json.dumps(tools_called,default=str), json.dumps(tool_errors,default=str),
            reflection_triggered,
            json.dumps([s.to_dict() for s in spans],default=str) if spans else None,
            correction_applied, guard_blocked, guard_score, tokens_used, latency_ms,
            model_used, episodic_hits, error)
    except Exception as e: log.warning(f"[OBS] persist_trace : {e}")
    lf = get_langfuse()
    if lf:
        try:
            lf.trace(id=trace_id, name="yasmine_turn", session_id=session_id,
                     input=user_message, output=assistant_reply,
                     metadata={"intention":intention,"reflection_triggered":reflection_triggered,
                               "guard_blocked":guard_blocked,"episodic_hits":episodic_hits})
            lf.generation(trace_id=trace_id, name="yasmine_reply", model=model_used,
                          output=assistant_reply, usage={"total_tokens":tokens_used})
            lf.score(trace_id=trace_id, name="reflection_ok", value=0 if reflection_triggered else 1)
        except Exception as e: log.debug(f"[OBS] Langfuse push : {e}")

_JUDGE_PROMPT = """Évalue cette interaction (location voitures) sur 4 critères (0-5 chacun).
Message: "{message}"
Réponse: "{reply}"
JSON uniquement: {{"utilite":0-5,"precision":0-5,"experience":0-5,"securite":0-5,"score_global":0-5,"axes_amelioration":[]}}"""

async def llm_judge_sample(traces, groq_client, sample_rate=0.1):
    import random
    sample = [t for t in traces if random.random() < sample_rate][:5]
    results = []
    for trace in sample:
        try:
            resp = await asyncio.to_thread(
                groq_client.chat.completions.create,
                model=settings.groq_model_fast, max_tokens=200, temperature=0,
                response_format={"type":"json_object"},
                messages=[{"role":"user","content":_JUDGE_PROMPT.format(
                    message=str(trace.get("user_message",""))[:300],
                    reply=str(trace.get("assistant_reply",""))[:400])}])
            data = json.loads(resp.choices[0].message.content)
            data["trace_id"] = trace.get("trace_id","")
            results.append(data)
            pool = await get_pool()
            await pool.execute("UPDATE agent_traces SET error=COALESCE(error,'')::text WHERE trace_id=$1",
                               trace.get("trace_id",""))
        except Exception as e: log.debug(f"[OBS] llm_judge : {e}")
    if results:
        avg = sum(r.get("score_global",0) for r in results)/len(results)
        log.info(f"[OBS] LLM-Judge score moyen: {avg:.1f}/5 sur {len(results)} traces")
    return results

class AgentMetrics:
    def __init__(self):
        self.total_turns=0; self.total_errors=0; self.reflection_triggered=0
        self.guard_blocked=0; self.tool_calls=0; self.tool_errors=0
        self.total_latency_ms=0; self.total_tokens=0
    def record_turn(self, latency_ms, tokens, reflection, guard, tool_count, tool_err_count, error):
        self.total_turns+=1; self.total_latency_ms+=latency_ms; self.total_tokens+=tokens
        self.tool_calls+=tool_count; self.tool_errors+=tool_err_count
        if reflection: self.reflection_triggered+=1
        if guard: self.guard_blocked+=1
        if error: self.total_errors+=1
    def to_prometheus(self):
        avg = self.total_latency_ms/self.total_turns if self.total_turns else 0
        return "\n".join([
            f"dourbia_turns_total {self.total_turns}",
            f"dourbia_errors_total {self.total_errors}",
            f"dourbia_reflection_total {self.reflection_triggered}",
            f"dourbia_guard_blocked_total {self.guard_blocked}",
            f"dourbia_avg_latency_ms {avg:.1f}",
            f"dourbia_total_tokens {self.total_tokens}",
        ])
    def to_dict(self):
        return {"total_turns":self.total_turns,"total_errors":self.total_errors,
                "reflection_rate":round(self.reflection_triggered/max(self.total_turns,1),3),
                "guard_block_rate":round(self.guard_blocked/max(self.total_turns,1),3),
                "avg_latency_ms":round(self.total_latency_ms/max(self.total_turns,1)),
                "avg_tokens_per_turn":round(self.total_tokens/max(self.total_turns,1))}

agent_metrics = AgentMetrics()
