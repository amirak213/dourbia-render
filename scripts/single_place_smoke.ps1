param(
    [string]$BaseUrl = "http://localhost:18100"
)

$ErrorActionPreference = "Stop"
$BaseUrl = $BaseUrl.TrimEnd("/")
$script:LastChatRequestAt = [DateTime]::MinValue
$script:ChatPacingSeconds = 3.1
$script:ChatTimeoutSeconds = 90

function Fix-Utf8 {
    param([string]$Text)
    if ($Text -and $Text.IndexOf([char]0x00C3) -ge 0) {
        try {
            return [Text.Encoding]::UTF8.GetString(
                [Text.Encoding]::GetEncoding(28591).GetBytes($Text)
            )
        }
        catch {
            return $Text
        }
    }
    return $Text
}

function Invoke-Api {
    param(
        [string]$Method,
        [string]$Path,
        $Body = $null,
        [int]$TimeoutSec = 45
    )

    $watch = [Diagnostics.Stopwatch]::StartNew()
    $result = [ordered]@{
        Ok = $false
        Code = 0
        Data = $null
        Error = ""
        Ms = 0
    }

    try {
        if ($null -ne $Body) {
            $json = ConvertTo-Json -InputObject $Body -Depth 20 -Compress
            $bytes = [Text.Encoding]::UTF8.GetBytes($json)
            $result.Data = Invoke-RestMethod `
                -Uri ($BaseUrl + $Path) `
                -Method $Method `
                -Body $bytes `
                -ContentType "application/json; charset=utf-8" `
                -TimeoutSec $TimeoutSec
        }
        else {
            $result.Data = Invoke-RestMethod `
                -Uri ($BaseUrl + $Path) `
                -Method $Method `
                -TimeoutSec $TimeoutSec
        }
        $result.Ok = $true
        $result.Code = 200
    }
    catch {
        $response = $_.Exception.Response
        if ($response) {
            try { $result.Code = [int]$response.StatusCode } catch {}
        }
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $result.Error = [string]$_.ErrorDetails.Message
        }
        else {
            $result.Error = $_.Exception.Message
        }
    }

    $watch.Stop()
    $result.Ms = $watch.ElapsedMilliseconds
    return [pscustomobject]$result
}

function Invoke-ChatAction {
    param(
        [string]$SessionId,
        [string]$Message,
        [hashtable]$Action
    )

    if ($script:LastChatRequestAt -ne [DateTime]::MinValue) {
        $elapsed = ([DateTime]::UtcNow - $script:LastChatRequestAt).TotalSeconds
        $wait = $script:ChatPacingSeconds - $elapsed
        if ($wait -gt 0) {
            Start-Sleep -Milliseconds ([int]($wait * 1000))
        }
    }
    $script:LastChatRequestAt = [DateTime]::UtcNow

    $request = @{
        session_id = $SessionId
        message = $Message
        language = "fr"
        action = $Action
    }
    $response = Invoke-Api -Method "Post" -Path "/api/chat" -Body $request -TimeoutSec $script:ChatTimeoutSeconds
    if (-not $response.Ok) {
        throw ("POST /api/chat a retourne HTTP {0}: {1}" -f $response.Code, $response.Error)
    }
    return $response
}

function Get-WizardOption {
    param(
        $WizardUi,
        [scriptblock]$Predicate,
        [string]$Description
    )
    $found = @($WizardUi.options | Where-Object { & $Predicate $_ } | Select-Object -First 1)
    if ($found.Count -eq 0) {
        throw ("Option wizard absente pour: " + $Description)
    }
    return $found[0]
}

function Test-SameId {
    param($Left, $Right)

    try {
        $leftId = [int][double]([string]$Left)
        $rightId = [int][double]([string]$Right)
        return ($leftId -eq $rightId)
    }
    catch {
        return $false
    }
}

function Test-FiniteNumber {
    param($Value)
    if ($null -eq $Value) {
        return $false
    }
    try {
        $number = [double]$Value
        return (-not [double]::IsNaN($number) -and -not [double]::IsInfinity($number))
    }
    catch {
        return $false
    }
}

$sessionId = [guid]::NewGuid().ToString()
$scenarioStartedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
$steps = New-Object System.Collections.ArrayList
$failureCause = ""
$selectResponse = $null
$confirmResponse = $null
$selectedOption = $null
$review = $null
$stageAfterSelect = "not-received"
$stageAfterConfirm = "not-received"
$responseError = ""
$tracebackFound = $false
$reviewCoherent = $false
$reviewStepCount = 0
$reviewStepIdMatches = $false
$logLines = @()

try {
    $chat = Invoke-ChatAction -SessionId $sessionId -Message "Demarrer un circuit a Carthage" -Action @{ type = "start_wizard" }
    [void]$steps.Add("start_wizard")
    $ui = $chat.Data.wizard_ui
    if (-not $ui -or $ui.state -ne "CUSTOMIZATION_BUDGET") {
        throw "Le demarrage du wizard n'a pas renvoye CUSTOMIZATION_BUDGET."
    }

    $budgetOption = Get-WizardOption $ui { param($o) $true } "budget"
    [void]$steps.Add("set_budget")
    $chat = Invoke-ChatAction -SessionId $sessionId -Message "Budget de test" -Action @{
        type = "set_budget"
        value = @{ type = [string]$budgetOption.value; amount = 100000 }
    }
    $ui = $chat.Data.wizard_ui
    if (-not $ui -or $ui.state -ne "CUSTOMIZATION_MOBILITY") {
        throw "La transition budget vers CUSTOMIZATION_MOBILITY a echoue."
    }

    $transport = Get-WizardOption $ui { param($o) $o.meta -and $o.meta.type -eq "transport" } "transport"
    $mobility = Get-WizardOption $ui { param($o) $o.meta -and $o.meta.type -eq "mobilite" } "mobilite"
    [void]$steps.Add("set_mobility")
    $chat = Invoke-ChatAction -SessionId $sessionId -Message "Deplacement a pied" -Action @{
        type = "set_mobility"
        value = @{
            transport = [string]$transport.value
            mobilite = [string]$mobility.value
        }
    }
    $ui = $chat.Data.wizard_ui
    if (-not $ui -or $ui.state -ne "CUSTOMIZATION_TIME") {
        throw "La transition mobilite vers CUSTOMIZATION_TIME a echoue."
    }

    [void]$steps.Add("set_time")
    $chat = Invoke-ChatAction -SessionId $sessionId -Message "Duree de sept heures" -Action @{
        type = "set_time"
        value = @{ duration_minutes = 420; start_time = "09:00"; end_time = "16:00" }
    }
    $ui = $chat.Data.wizard_ui
    if (-not $ui -or $ui.state -ne "CUSTOMIZATION_PREFERENCES") {
        throw "La transition duree vers CUSTOMIZATION_PREFERENCES a echoue."
    }

    [void]$steps.Add("set_preferences")
    $chat = Invoke-ChatAction -SessionId $sessionId -Message "Preferences de visite" -Action @{
        type = "set_preferences"
        value = @{ epoques = @(); fonctions = @() }
    }
    $ui = $chat.Data.wizard_ui
    if (-not $ui -or $ui.state -ne "PLACE_SELECTION") {
        throw "La transition preferences vers PLACE_SELECTION a echoue."
    }

    $optionsById = @{}
    $pageCount = 0
    while (-not ($optionsById.ContainsKey("1") -and $optionsById.ContainsKey("3"))) {
        foreach ($option in @($ui.options)) {
            if (Test-SameId $option.value 1) {
                $optionsById["1"] = $option
            }
            if (Test-SameId $option.value 3) {
                $optionsById["3"] = $option
            }
        }
        if ($optionsById.ContainsKey("1") -and $optionsById.ContainsKey("3")) {
            break
        }
        if (-not $ui.has_more -or $pageCount -ge 30) {
            throw ("Les options wizard n'exposent pas les ids 1 et 3 (pages consultees: {0})." -f ($pageCount + 1))
        }
        $pageCount++
        [void]$steps.Add("load_more_places")
        $chat = Invoke-ChatAction -SessionId $sessionId -Message "Afficher plus de lieux" -Action @{ type = "load_more_places" }
        $ui = $chat.Data.wizard_ui
        if (-not $ui -or $ui.state -ne "PLACE_SELECTION") {
            throw "La pagination des options a quitte PLACE_SELECTION."
        }
    }

    $selectedOption = $optionsById["1"]
    [void]$steps.Add(("select_places(id={0}, name={1})" -f $selectedOption.value, (Fix-Utf8 ([string]$selectedOption.label))))
    try {
        $selectResponse = Invoke-ChatAction -SessionId $sessionId -Message "Selectionner le Theatre" -Action @{
            type = "select_places"
            value = @([string]$selectedOption.value)
        }
        $uiAfterSelect = $selectResponse.Data.wizard_ui
        if ($uiAfterSelect) {
            $stageAfterSelect = [string]$uiAfterSelect.state
        }
        if ($uiAfterSelect -and $uiAfterSelect.circuit) {
            $review = $uiAfterSelect
        }
        if ($selectResponse.Data.answer) {
            $responseError = [string]$selectResponse.Data.answer
        }
    }
    catch {
        $stageAfterSelect = "HTTP/API error"
        $failureCause = $_.Exception.Message
        $responseError = $failureCause
    }

    [void]$steps.Add("confirm_circuit")
    try {
        $confirmResponse = Invoke-ChatAction -SessionId $sessionId -Message "Confirmer le circuit" -Action @{
            type = "confirm_circuit"
        }
        $uiAfterConfirm = $confirmResponse.Data.wizard_ui
        if ($uiAfterConfirm) {
            $stageAfterConfirm = [string]$uiAfterConfirm.state
            if ($uiAfterConfirm.circuit) {
                $review = $uiAfterConfirm
            }
        }
        if ($confirmResponse.Data.answer) {
            $responseError = [string]$confirmResponse.Data.answer
        }
    }
    catch {
        $stageAfterConfirm = "HTTP/API error"
        $responseError = $_.Exception.Message
        if (-not $failureCause) {
            $failureCause = $responseError
        }
    }
}
catch {
    if (-not $failureCause) {
        $failureCause = $_.Exception.Message
    }
}

Write-Output ("SessionId: {0}" -f $sessionId)
Write-Output ("Heure de debut des logs: {0}" -f $scenarioStartedAt)
Write-Output ("Etapes envoyees: {0}" -f ($steps -join " -> "))
Write-Output ("Etat/stage apres select_places: {0}" -f $stageAfterSelect)
Write-Output ("Etat/stage apres confirm_circuit: {0}" -f $stageAfterConfirm)
if ($responseError) {
    Write-Output ("Texte d'erreur/reponse: {0}" -f $responseError)
}
elseif ($failureCause) {
    Write-Output ("Texte d'erreur: {0}" -f $failureCause)
}
else {
    Write-Output "Texte d'erreur/reponse: aucun."
}

if ($review -and $review.circuit) {
    $stops = @($review.circuit.monuments)
    $reviewStepCount = $stops.Count
    Write-Output ("Revue presente: true; nombre d'etapes: {0}" -f $reviewStepCount)
    foreach ($stop in $stops) {
        Write-Output ("Etape: ordre={0}; nom={1}; duree_min={2}" -f $stop.order, (Fix-Utf8 ([string]$stop.name)), $stop.visit_duration_min)
    }
    $totalDuration = $review.circuit.total_duration_min
    $reviewCoherent = $true
    $route = $review.circuit.route
    if ($null -eq $route) {
        $reviewCoherent = $false
        $routeSegments = @()
    }
    else {
        $routeSegments = @($route.segments)
    }
    $totalDistance = 0.0
    foreach ($segment in $routeSegments) {
        if (-not (Test-FiniteNumber $segment.distance_km)) {
            $reviewCoherent = $false
        }
        else {
            $totalDistance += [double]$segment.distance_km
        }
    }
    Write-Output ("Totaux: duree_min={0}; distance_km={1}" -f $totalDuration, $totalDistance)

    $reviewCoherent = $reviewCoherent -and (Test-FiniteNumber $totalDuration) -and (Test-FiniteNumber $totalDistance)
    foreach ($stop in $stops) {
        if (-not (Test-FiniteNumber $stop.order) -or
            [string]::IsNullOrWhiteSpace([string]$stop.name) -or
            -not (Test-FiniteNumber $stop.visit_duration_min)) {
            $reviewCoherent = $false
        }
    }
    $reviewStepIdMatches = ($reviewStepCount -eq 1 -and (Fix-Utf8 ([string]$stops[0].name)).Trim() -eq (Fix-Utf8 ([string]$selectedOption.label)).Trim())
    Write-Output ("Coherence revue (valeurs numeriques non nulles/non NaN, nom et ordre presents): {0}" -f $reviewCoherent)
    Write-Output ("Etape unique coherente avec l'option wizard id=1: {0}" -f $reviewStepIdMatches)
}
else {
    Write-Output "Revue presente: false."
}

$savedErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $rawLogLines = & docker logs --since $scenarioStartedAt dourbia-backend-render-test 2>&1
    $logExitCode = $LASTEXITCODE
    $logLines = @($rawLogLines | ForEach-Object { [string]$_ })
}
catch {
    $logExitCode = -1
    $logLines = @([string]$_.Exception.Message)
}
finally {
    $ErrorActionPreference = $savedErrorActionPreference
}

if ($logExitCode -ne 0) {
    Write-Output ("Docker logs: erreur (code {0})." -f $logExitCode)
}
$matchingLogs = @($logLines | Where-Object {
    $_ -match "(?i)randrange|Traceback|ERROR|CIRCUIT_ADJUSTMENT"
})
Write-Output "Lignes de logs correspondantes:"
if ($matchingLogs.Count -eq 0) {
    Write-Output "Aucune."
}
else {
    foreach ($line in $matchingLogs) {
        Write-Output $line
        if ($line -match "(?i)Traceback") {
            $tracebackFound = $true
        }
    }
}

if ($review -and $reviewStepCount -eq 1 -and $reviewStepIdMatches -and $reviewCoherent -and -not $tracebackFound) {
    Write-Output "Verdict: PASS"
    exit 0
}

if (-not $failureCause) {
    if ($tracebackFound) {
        $failureCause = "Traceback present dans les logs."
    }
    elseif (-not $review) {
        $failureCause = ("Aucune revue produite; etat apres confirm_circuit: {0}." -f $stageAfterConfirm)
    }
    elseif ($reviewStepCount -ne 1) {
        $failureCause = ("Nombre d'etapes inattendu: {0}." -f $reviewStepCount)
    }
    elseif (-not $reviewStepIdMatches) {
        $failureCause = "L'etape de revue ne correspond pas au nom de l'option wizard id=1."
    }
    elseif (-not $reviewCoherent) {
        $failureCause = "La revue contient une valeur nulle, NaN, infinie ou incoherente."
    }
}
Write-Output ("Verdict: FAIL - {0}" -f $failureCause)
exit 1
