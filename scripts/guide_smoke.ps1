param(
    [string]$BaseUrl = "http://localhost:18100"
)

$ErrorActionPreference = "Stop"
$BaseUrl = $BaseUrl.TrimEnd("/")
$script:Results = New-Object System.Collections.ArrayList
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

function Invoke-DatabaseQuery {
    param(
        [string]$Container,
        [string]$Database,
        [string]$User,
        [string]$Query
    )

    $output = & docker exec $Container psql `
        -X -q -A -t `
        -U $User `
        -d $Database `
        -c $Query 2>&1
    if ($LASTEXITCODE -ne 0) {
        $safeError = (@($output) -join " ").Trim()
        throw ("Lecture PostgreSQL impossible (aucun mot de passe n'est affiche): " + $safeError)
    }
    return @($output)
}

function Get-DatabaseChoice {
    $container = "dourbia_restore_test"
    $dbName = "dourbia_render_test"
    $dbUser = (& docker exec $container printenv POSTGRES_USER 2>$null | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($dbUser)) {
        $dbUser = "postgres"
    }

    $membershipQuery = @"
SELECT id_monument::text
FROM tab_circuit_monument
WHERE id_circuit::text = '1'
  AND id_monument::text IN ('1', '3')
ORDER BY id_monument::bigint
"@
    $members = @(Invoke-DatabaseQuery -Container $container -Database $dbName -User $dbUser -Query $membershipQuery |
        Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
        ForEach-Object { ([string]$_).Trim() })
    if ($members -notcontains "1" -or $members -notcontains "3") {
        throw ("Le circuit 1 ne contient pas les deux lieux requis (ids trouves: {0})." -f ($members -join ","))
    }

    $descriptionOneQuery = "SELECT id::text || '|' || encode(convert_to(COALESCE(description_fr, ''), 'UTF8'), 'base64') FROM monuments WHERE id = 1"
    $descriptionThreeQuery = "SELECT id::text || '|' || encode(convert_to(COALESCE(description_fr, ''), 'UTF8'), 'base64') FROM monuments WHERE id = 3"
    $descriptionOneRow = @(Invoke-DatabaseQuery -Container $container -Database $dbName -User $dbUser -Query $descriptionOneQuery |
        Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
        Select-Object -First 1)
    $descriptionThreeRow = @(Invoke-DatabaseQuery -Container $container -Database $dbName -User $dbUser -Query $descriptionThreeQuery |
        Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
        Select-Object -First 1)
    if ($descriptionOneRow.Count -eq 0 -or $descriptionThreeRow.Count -eq 0) {
        throw "La lecture directe des descriptions des monuments id=1 et id=3 a renvoye une ligne manquante."
    }

    $descriptionOneParts = ([string]$descriptionOneRow[0]) -split "\|", 2
    $descriptionThreeParts = ([string]$descriptionThreeRow[0]) -split "\|", 2
    if ($descriptionOneParts.Count -ne 2 -or $descriptionThreeParts.Count -ne 2) {
        throw "La lecture directe des descriptions a renvoye un format inattendu."
    }
    $descriptionOne = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($descriptionOneParts[1]))
    $descriptionThree = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($descriptionThreeParts[1]))
    if ([string]::IsNullOrWhiteSpace($descriptionOne)) {
        throw "Le monument id=1 ne contient pas de description_fr exploitable."
    }
    if (-not [string]::IsNullOrWhiteSpace($descriptionThree)) {
        throw "Le monument id=3 contient une description_fr alors qu'elle est attendue vide."
    }

    return [pscustomobject]@{
        CircuitId = "1"
        DescribedId = "1"
        UndescribedId = "3"
        Description = $descriptionOne
        UndescribedDescription = $descriptionThree
    }
}

function Get-Monument {
    param($Monuments, [string]$Id)
    $matches = @($Monuments | Where-Object { [string]$_.id -eq $Id } | Select-Object -First 1)
    if ($matches.Count -eq 0) {
        throw ("Monument id={0} absent de GET /api/monuments." -f $Id)
    }
    $matches[0].name_fr = Fix-Utf8 ([string]$matches[0].name_fr)
    return $matches[0]
}

function Get-GuideSession {
    param()

    $sessionId = [guid]::NewGuid().ToString()
    $steps = New-Object System.Collections.ArrayList
    $chat = Invoke-ChatAction -SessionId $sessionId -Message "Demarrer un circuit a Carthage" -Action @{ type = "start_wizard" }
    [void]$steps.Add("start_wizard")
    $ui = $chat.Data.wizard_ui
    if (-not $ui -or $ui.state -ne "CUSTOMIZATION_BUDGET") {
        throw ("Le demarrage du wizard n'a pas renvoye CUSTOMIZATION_BUDGET.")
    }

    $budgetOption = Get-WizardOption $ui { param($o) $true } "budget"
    $chat = Invoke-ChatAction -SessionId $sessionId -Message "Budget de test" -Action @{
        type = "set_budget"
        value = @{ type = [string]$budgetOption.value; amount = 100000 }
    }
    [void]$steps.Add(("set_budget(type={0}, amount=100000)" -f $budgetOption.value))
    $ui = $chat.Data.wizard_ui
    if (-not $ui -or $ui.state -ne "CUSTOMIZATION_MOBILITY") {
        throw "La transition budget vers CUSTOMIZATION_MOBILITY a echoue."
    }

    $transport = Get-WizardOption $ui { param($o) $o.meta -and $o.meta.type -eq "transport" } "transport"
    $mobility = Get-WizardOption $ui { param($o) $o.meta -and $o.meta.type -eq "mobilite" } "mobilite"
    $chat = Invoke-ChatAction -SessionId $sessionId -Message "Deplacement a pied" -Action @{
        type = "set_mobility"
        value = @{
            transport = [string]$transport.value
            mobilite = [string]$mobility.value
        }
    }
    [void]$steps.Add(("set_mobility(transport={0}, mobilite={1})" -f $transport.value, $mobility.value))
    $ui = $chat.Data.wizard_ui
    if (-not $ui -or $ui.state -ne "CUSTOMIZATION_TIME") {
        throw "La transition mobilite vers CUSTOMIZATION_TIME a echoue."
    }

    $chat = Invoke-ChatAction -SessionId $sessionId -Message "Duree de sept heures" -Action @{
        type = "set_time"
        value = @{ duration_minutes = 420; start_time = "09:00"; end_time = "16:00" }
    }
    [void]$steps.Add("set_time(duration_minutes=420, start_time=09:00, end_time=16:00)")
    $ui = $chat.Data.wizard_ui
    if (-not $ui -or $ui.state -ne "CUSTOMIZATION_PREFERENCES") {
        throw "La transition duree vers CUSTOMIZATION_PREFERENCES a echoue."
    }

    $chat = Invoke-ChatAction -SessionId $sessionId -Message "Preferences de visite" -Action @{
        type = "set_preferences"
        value = @{ epoques = @(); fonctions = @() }
    }
    [void]$steps.Add("set_preferences(epoques=[], fonctions=[])")
    $ui = $chat.Data.wizard_ui
    if (-not $ui -or $ui.state -ne "PLACE_SELECTION") {
        throw "La transition preferences vers PLACE_SELECTION a echoue."
    }

    $selectedOptions = @{}
    $pageCount = 0
    while (-not ($selectedOptions.ContainsKey("1") -and $selectedOptions.ContainsKey("3"))) {
        foreach ($option in @($ui.options)) {
            $optionId = [string]$option.value
            if ($optionId -eq "1" -or $optionId -eq "3") {
                $selectedOptions[$optionId] = $option
            }
        }
        if ($selectedOptions.ContainsKey("1") -and $selectedOptions.ContainsKey("3")) {
            break
        }
        if (-not $ui.has_more -or $pageCount -ge 30) {
            throw ("Les options du wizard n'exposent pas les deux ids requis (pages consultees: {0}; ids trouves: {1})." -f ($pageCount + 1), (@($selectedOptions.Keys) -join ","))
        }
        $pageCount++
        $chat = Invoke-ChatAction -SessionId $sessionId -Message "Afficher plus de lieux" -Action @{ type = "load_more_places" }
        [void]$steps.Add("load_more_places")
        $ui = $chat.Data.wizard_ui
        if (-not $ui -or $ui.state -ne "PLACE_SELECTION") {
            throw "La pagination des options a quitte PLACE_SELECTION."
        }
    }

    $selectedIds = @([string]$selectedOptions["1"].value, [string]$selectedOptions["3"].value)
    $selectedNames = @(
        (Fix-Utf8 ([string]$selectedOptions["1"].label)),
        (Fix-Utf8 ([string]$selectedOptions["3"].label))
    )

    $chat = Invoke-ChatAction -SessionId $sessionId -Message "Selectionner le lieu affiche" -Action @{
        type = "select_places"
        value = $selectedIds
    }
    [void]$steps.Add(("select_places(ids={0}, names={1})" -f ($selectedIds -join ","), ($selectedNames -join " | ")))
    $ui = $chat.Data.wizard_ui
    if (-not $ui -or $ui.state -ne "CIRCUIT_REVIEW" -or -not $ui.circuit) {
        throw ("La generation du circuit n'a pas renvoye CIRCUIT_REVIEW (etat recu: {0})." -f $(if ($ui) { $ui.state } else { "null" }))
    }
    $review = $ui
    if ($review.budget_ok -eq $false) {
        throw ("Le circuit est rejete pour depassement de budget: total={0}, budget={1}." -f $review.circuit.total_price, $review.circuit.budget_max)
    }
    $reviewNames = @($review.circuit.monuments | ForEach-Object { Fix-Utf8 ([string]$_.name).Trim() })
    foreach ($selectedName in $selectedNames) {
        if ($reviewNames -notcontains $selectedName.Trim()) {
            throw ("Le circuit genere ne contient pas le lieu selectionne '{0}'. Etapes: {1}" -f $selectedName, ($reviewNames -join ", "))
        }
    }

    $confirmOption = Get-WizardOption $ui { param($o) [string]$o.value -eq "confirm_circuit" } "confirmation du circuit"
    $chat = Invoke-ChatAction -SessionId $sessionId -Message "Confirmer le circuit" -Action @{
        type = [string]$confirmOption.value
    }
    [void]$steps.Add("confirm_circuit")
    $ui = $chat.Data.wizard_ui
    if (-not $ui -or $ui.state -ne "GUIDE_MODE_READY") {
        throw "La confirmation du circuit n'a pas conduit a GUIDE_MODE_READY."
    }

    $yesOption = Get-WizardOption $ui { param($o) [string]$o.label -match "^(Oui|Yes)" } "activation du mode guide"
    $chat = Invoke-ChatAction -SessionId $sessionId -Message "Activer le guide GPS" -Action @{
        type = "confirm_guide_mode"
        value = [string]$yesOption.value
    }
    [void]$steps.Add(("confirm_guide_mode(value={0})" -f $yesOption.value))
    if ($chat.Data.wizard_ui -and $chat.Data.wizard_ui.state -ne "IDLE") {
        throw ("Le wizard n'est pas termine apres la confirmation du guide: {0}" -f $chat.Data.wizard_ui.state)
    }

    return [pscustomobject]@{
        SessionId = $sessionId
        SelectedIds = $selectedIds
        SelectedNames = $selectedNames
        WizardSteps = @($steps)
        Review = $review
    }
}

function Get-HaversineMeters {
    param([double]$Lat1, [double]$Lon1, [double]$Lat2, [double]$Lon2)
    $toRadians = [Math]::PI / 180.0
    $dLat = ($Lat2 - $Lat1) * $toRadians
    $dLon = ($Lon2 - $Lon1) * $toRadians
    $a = [Math]::Sin($dLat / 2) * [Math]::Sin($dLat / 2) +
        [Math]::Cos($Lat1 * $toRadians) * [Math]::Cos($Lat2 * $toRadians) *
        [Math]::Sin($dLon / 2) * [Math]::Sin($dLon / 2)
    return 6371000.0 * 2.0 * [Math]::Atan2([Math]::Sqrt($a), [Math]::Sqrt(1.0 - $a))
}

function Add-TestResult {
    param(
        [string]$Id,
        [string]$Status,
        [long]$Ms,
        [string]$Detail
    )
    $row = [pscustomobject]@{
        Id = $Id
        Status = $Status
        Ms = $Ms
        Detail = $Detail
    }
    [void]$script:Results.Add($row)
    Write-Output ("{0} {1} ({2} ms) - {3}" -f $Id, $Status, $Ms, $Detail)
}

function Get-DescriptionOverlap {
    param([string]$Description, [string]$Answer)
    $stopWords = @("avec", "dans", "pour", "mais", "plus", "dont", "elle", "elles", "leur", "leurs", "ainsi", "comme", "entre", "cette", "tout", "tous", "sont", "avait", "etre", "depuis", "selon", "par", "sur", "que", "qui", "les", "des", "une", "dans", "aux", "est", "son", "ses", "ses", "cet", "ces", "ont", "ete", "pas", "the")
    $descriptionWords = [regex]::Matches($Description.ToLowerInvariant(), "[\p{L}]{4,}") |
        ForEach-Object { $_.Value } |
        Where-Object { $stopWords -notcontains $_ } |
        Select-Object -First 35
    $answerWords = @{}
    foreach ($match in [regex]::Matches($Answer.ToLowerInvariant(), "[\p{L}]{4,}")) {
        $answerWords[$match.Value] = $true
    }
    $overlap = @($descriptionWords | Where-Object { $answerWords.ContainsKey($_) } | Select-Object -Unique)
    return ,$overlap
}

function Get-SourceLineNumber {
    param([string]$Path, [string]$Text)
    $match = @(Select-String -LiteralPath $Path -SimpleMatch -Pattern $Text | Select-Object -First 1)
    if ($match.Count -eq 0) {
        return "not-found"
    }
    return [string]$match[0].LineNumber
}

$fatal = $false
$db = $null
$monuments = @()
$scenario = $null
$positionTheatre = $null

try {
    $monumentsResponse = Invoke-Api -Method "Get" -Path "/api/monuments" -TimeoutSec 30
    if (-not $monumentsResponse.Ok) {
        throw ("GET /api/monuments a retourne HTTP {0}: {1}" -f $monumentsResponse.Code, $monumentsResponse.Error)
    }
    $monuments = @($monumentsResponse.Data.monuments)
    $db = Get-DatabaseChoice
    $describedMonument = Get-Monument $monuments $db.DescribedId
    $undescMonument = Get-Monument $monuments $db.UndescribedId

    $descriptionOne = ((Fix-Utf8 $db.Description) -replace "\s+", " ").Trim()
    Write-Output ("Selection source: circuit {0}; id={1} '{2}', id={3} '{4}'." -f `
        $db.CircuitId, $db.DescribedId, $describedMonument.name_fr, $db.UndescribedId, $undescMonument.name_fr)
    Write-Output ("Description lue directement WHERE id=1 (80c): {0}" -f $descriptionOne.Substring(0, [Math]::Min(80, $descriptionOne.Length)))
    Write-Output "Description lue directement WHERE id=3: vide."
}
catch {
    Add-TestResult "A" "FAIL" 0 ("Preparation impossible: " + $_.Exception.Message)
    Add-TestResult "B" "FAIL" 0 "Prerequis A non disponible."
    Add-TestResult "C" "FAIL" 0 "Prerequis A/B non disponible."
    Add-TestResult "D" "INFO" 0 "Prerequis base/API non disponible; test informatif non execute."
    Add-TestResult "E" "FAIL" 0 "Prerequis A non disponible."
    $fatal = $true
}

if (-not $fatal) {
    $watchA = [Diagnostics.Stopwatch]::StartNew()
    try {
        $scenario = Get-GuideSession
        Write-Output ("Etapes wizard envoyees: {0}" -f ($scenario.WizardSteps -join " -> "))
        Write-Output ("Lieux effectivement selectionnes depuis les options wizard: id=1 '{0}' et id=3 '{1}'." -f `
            $scenario.SelectedNames[0], $scenario.SelectedNames[1])
        $orderedStops = @($scenario.Review.circuit.monuments | Sort-Object { [int]$_.order })
        $stopSummary = @($orderedStops | ForEach-Object {
            "{0}='{1}'" -f $_.order, (Fix-Utf8 ([string]$_.name))
        })
        Write-Output ("Ordre du circuit genere: {0}" -f ($stopSummary -join " -> "))

        $status = Invoke-Api -Method "Get" -Path ("/api/guide-status/" + $scenario.SessionId) -TimeoutSec 30
        if (-not $status.Ok) {
            throw ("GET /api/guide-status a retourne HTTP {0}: {1}" -f $status.Code, $status.Error)
        }
        $circuitName = Fix-Utf8 ([string]$status.Data.circuit_nom)
        if (-not $status.Data.mode_guide_actif -or [string]::IsNullOrWhiteSpace([string]$status.Data.circuit_id) -or [string]::IsNullOrWhiteSpace($circuitName)) {
            throw ("guide-status incomplet: mode_guide_actif={0}, circuit_id={1}, circuit_nom={2}" -f $status.Data.mode_guide_actif, $status.Data.circuit_id, $circuitName)
        }
        Add-TestResult "A" "PASS" ($watchA.ElapsedMilliseconds + $status.Ms) ("mode_guide_actif=true, circuit_id={0}, circuit_nom='{1}', session={2}" -f $status.Data.circuit_id, $circuitName, $scenario.SessionId)
    }
    catch {
        Add-TestResult "A" "FAIL" $watchA.ElapsedMilliseconds $_.Exception.Message
        $fatal = $true
    }
    $watchA.Stop()

    if ($null -ne $scenario) {
        $watchB = [Diagnostics.Stopwatch]::StartNew()
        try {
            $positionTheatre = Invoke-Api -Method "Post" -Path "/api/position" -Body @{
                session_id = $scenario.SessionId
                latitude = [double]$describedMonument.latitude
                longitude = [double]$describedMonument.longitude
                langue = "FR"
            } -TimeoutSec 45
            if (-not $positionTheatre.Ok) {
                throw ("POST /api/position a retourne HTTP {0}: {1}" -f $positionTheatre.Code, $positionTheatre.Error)
            }
            if (-not $positionTheatre.Data.triggered -or -not (Test-SameId $positionTheatre.Data.monument_id $db.DescribedId)) {
                throw ("triggered={0}, monument_id={1}, monument={2}; attendu id={3}." -f $positionTheatre.Data.triggered, $positionTheatre.Data.monument_id, $positionTheatre.Data.monument, $db.DescribedId)
            }
            $positionName = Fix-Utf8 ([string]$positionTheatre.Data.monument)
            Add-TestResult "B" "PASS" $positionTheatre.Ms ("triggered=true, monument_id={0}, monument='{1}', distance_m={2}" -f $positionTheatre.Data.monument_id, $positionName, $positionTheatre.Data.distance_m)
        }
        catch {
            Add-TestResult "B" "FAIL" $watchB.ElapsedMilliseconds $_.Exception.Message
            $fatal = $true
        }
        $watchB.Stop()

        if ($null -ne $positionTheatre -and $positionTheatre.Ok -and $positionTheatre.Data.triggered) {
            $watchC = [Diagnostics.Stopwatch]::StartNew()
            try {
                $message = "Parle-moi de Theatre"
                $chat = Invoke-ChatAction -SessionId $scenario.SessionId -Message $message -Action $null
                $answer = Fix-Utf8 ([string]$chat.Data.answer)
                $overlap = Get-DescriptionOverlap -Description (Fix-Utf8 $db.Description) -Answer $answer
                $answerLanguage = [string]$chat.Data.memory_context.preferred_language
                $isFrench = $answerLanguage -match "^fr"
                if ([string]::IsNullOrWhiteSpace($answer) -or -not $isFrench -or $overlap.Count -lt 2) {
                    throw ("reponse narrative invalide: vide={0}, langue={1}, chevauchement description={2}" -f [string]::IsNullOrWhiteSpace($answer), $answerLanguage, ($overlap -join ", "))
                }
                $excerpt = $answer.Substring(0, [Math]::Min(200, $answer.Length))
                Add-TestResult "C" "PASS" $chat.Ms ("narratif FR non vide; mots communs avec description: {0}; extrait 200c: {1}" -f ($overlap -join ", "), $excerpt)
            }
            catch {
                Add-TestResult "C" "FAIL" $watchC.ElapsedMilliseconds $_.Exception.Message
                $fatal = $true
            }
            $watchC.Stop()
        }
        else {
            Add-TestResult "C" "FAIL" 0 "Non execute: le test B n'a pas detecte le monument."
            $fatal = $true
        }
    }
    else {
        Add-TestResult "B" "FAIL" 0 "Non execute: le scenario A n'a pas ete initialise."
        Add-TestResult "C" "FAIL" 0 "Non execute: le scenario A n'a pas ete initialise."
    }

    $watchD = [Diagnostics.Stopwatch]::StartNew()
    $dStartedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    try {
        if ($null -eq $scenario) {
            throw "Non execute: le scenario A n'a pas cree de session."
        }
        $positionD = Invoke-Api -Method "Post" -Path "/api/position" -Body @{
            session_id = $scenario.SessionId
            latitude = [double]$undescMonument.latitude
            longitude = [double]$undescMonument.longitude
            langue = "FR"
        } -TimeoutSec 45
        if (-not $positionD.Ok -or -not $positionD.Data.triggered -or -not (Test-SameId $positionD.Data.monument_id $db.UndescribedId)) {
            throw ("position sans description: HTTP={0}, triggered={1}, monument_id={2}, attendu={3}" -f $positionD.Code, $positionD.Data.triggered, $positionD.Data.monument_id, $db.UndescribedId)
        }
        $messageD = "Parle-moi de Monastere de Bigua"
        $chatD = Invoke-ChatAction -SessionId $scenario.SessionId -Message $messageD -Action $null
        if (-not $chatD.Ok) {
            throw ("POST /api/chat sans description a retourne HTTP {0}: {1}" -f $chatD.Code, $chatD.Error)
        }
        $answerD = [string]$chatD.Data.answer
        $excerptD = $answerD.Substring(0, [Math]::Min(200, $answerD.Length))
        Add-TestResult "D" "INFO" $watchD.ElapsedMilliseconds ("sans jugement semantique; meme session={0}, monument_id={1}, texte exact (200 premiers caracteres): {2}" -f $scenario.SessionId, $positionD.Data.monument_id, $excerptD)
    }
    catch {
        Add-TestResult "D" "INFO" $watchD.ElapsedMilliseconds ("scenario informatif non termine: " + $_.Exception.Message)
    }
    $watchD.Stop()

    try {
        $logContainer = "dourbia-backend-render-test"
        $savedErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $rawLogOutput = & docker logs --since $dStartedAt $logContainer 2>&1
            $logExitCode = $LASTEXITCODE
            $logOutput = @($rawLogOutput | ForEach-Object { [string]$_ })
        }
        finally {
            $ErrorActionPreference = $savedErrorActionPreference
        }
        if ($logExitCode -ne 0) {
            Write-Output ("Logs D: docker logs impossible depuis {0}: {1}" -f $dStartedAt, ((@($logOutput) -join " ").Trim()))
        }
        else {
            $matchingLogs = @($logOutput | Where-Object {
                ([string]$_) -match "(?i)web_search|ddgs|tavily|WEB_|recherche web"
            })
            Write-Output ("Logs D depuis {0}, conteneur {1}:" -f $dStartedAt, $logContainer)
            if ($matchingLogs.Count -eq 0) {
                Write-Output "  Aucune ligne correspondante; cela ne prouve pas qu'aucune tentative n'a eu lieu si elle n'est pas journalisee."
            }
            else {
                foreach ($logLine in $matchingLogs) {
                    $safeLogLine = [string]$logLine -replace "(?i)((?:api[_-]?key|secret|password|token)\s*[:=]\s*)\S+", '$1[REDACTED]'
                    Write-Output ("  " + $safeLogLine)
                }
            }
        }
    }
    catch {
        Write-Output ("Logs D: lecture impossible: " + $_.Exception.Message)
    }

    $orchestratorPath = Join-Path $PSScriptRoot "..\AgentPrincipal\orchestrateur.py"
    $workerPath = Join-Path $PSScriptRoot "..\AgentPrincipal\agents\historical\worker.py"
    $orchestratorEnvLine = Get-SourceLineNumber -Path $orchestratorPath -Text "WEB_SEARCH_ENABLED"
    $workerEnvLine = Get-SourceLineNumber -Path $workerPath -Text "os.environ.get(`"WEB_SEARCH_ENABLED`""
    $hardcodedLine = Get-SourceLineNumber -Path $orchestratorPath -Text "web_search_enabled=True"
    Write-Output ("Code WEB_SEARCH_ENABLED: AgentPrincipal/orchestrateur.py:{0} lit la variable (defaut false); AgentPrincipal/agents/historical/worker.py:{1} la relit independamment." -f $orchestratorEnvLine, $workerEnvLine)
    Write-Output ("Recherche web forcee pour un monument sans description: AgentPrincipal/orchestrateur.py:{0} passe web_search_enabled=True en dur." -f $hardcodedLine)

    $watchE = [Diagnostics.Stopwatch]::StartNew()
    try {
        if ($null -eq $scenario) {
            throw "Non execute: le scenario A n'a pas cree de session."
        }
        $stops = @($scenario.Review.circuit.monuments)
        $distances = @()
        foreach ($stop in $stops) {
            if ($null -ne $stop.latitude -and $null -ne $stop.longitude) {
                $distances += Get-HaversineMeters -Lat1 0.0 -Lon1 0.0 -Lat2 ([double]$stop.latitude) -Lon2 ([double]$stop.longitude)
            }
        }
        if ($distances.Count -eq 0) {
            throw "Aucune etape avec coordonnees dans le circuit genere, distance > 1 km non verifiable."
        }
        $minimumDistance = ($distances | Measure-Object -Minimum).Minimum
        if ($minimumDistance -le 1000) {
            throw ("La position (0,0) n'est pas a plus de 1 km de chaque etape: distance minimale={0} m." -f [Math]::Round($minimumDistance, 1))
        }
        $positionE = Invoke-Api -Method "Post" -Path "/api/position" -Body @{
            session_id = $scenario.SessionId
            latitude = 0.0
            longitude = 0.0
            langue = "FR"
        } -TimeoutSec 45
        if (-not $positionE.Ok -or $positionE.Data.triggered) {
            throw ("position eloignee: HTTP={0}, triggered={1}, monument_id={2}" -f $positionE.Code, $positionE.Data.triggered, $positionE.Data.monument_id)
        }
        Add-TestResult "E" "PASS" $watchE.ElapsedMilliseconds ("triggered=false a (0,0), distance minimale a une etape={0} m, meme session={1}" -f [Math]::Round($minimumDistance, 1), $scenario.SessionId)
    }
    catch {
        Add-TestResult "E" "FAIL" $watchE.ElapsedMilliseconds $_.Exception.Message
        $fatal = $true
    }
    $watchE.Stop()
}

Write-Output ""
Write-Output "Bilan:"
$script:Results | Format-Table -Property Id, Status, Ms, Detail -Wrap -AutoSize | Out-String -Width 240 | Write-Output
$failedRequired = @($script:Results | Where-Object {
    $_.Status -eq "FAIL" -and $_.Id -in @("A", "B", "C", "E")
})
if ($failedRequired.Count -gt 0) {
    exit 1
}
exit 0
