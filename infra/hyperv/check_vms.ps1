<#
.SYNOPSIS
  Diagnostic en lecture seule des 3 VM du POC RT_Meteo_PG : Hyper-V, reseau de l'hote, ping, port 22, banniere SSH.

.DESCRIPTION
  Ne modifie rien. A lancer apres create_vms.ps1 (ou quand SSH ne repond pas) :
  - commutateur interne, adresse passerelle sur l'hote (doublon = cause classique d'echec SSH), NAT ;
  - etat des VM, commutateur utilise, IP vues par Hyper-V ;
  - pour chaque VM : ping, ouverture du port 22 et banniere SSH, presence d'une ancienne cle d'hote dans known_hosts ;
  - avec -TrySsh : une connexion ssh sans saisie (BatchMode) pour distinguer "sshd absent" de "authentification refusee".

.PARAMETER Subnet
  Trois premiers octets du reseau /24. Defaut : 192.168.50.
.PARAMETER SwitchName
  Commutateur interne attendu. Defaut : compa-net (meme valeur que create_vms.ps1).
.PARAMETER AdminUser
  Utilisateur des VM, pour -TrySsh. Defaut : admin01.
.PARAMETER TrySsh
  Tente aussi 'ssh <AdminUser>@<ip> hostname' sans mot de passe (echoue sans cle SSH, c'est attendu).

.EXAMPLE
  .\check_vms.ps1
.EXAMPLE
  .\check_vms.ps1 -TrySsh
#>
[CmdletBinding()]
param(
    [string]$Subnet     = '192.168.50',
    [string]$SwitchName = 'compa-net',
    [string]$AdminUser  = 'admin01',
    [switch]$TrySsh
)

$ErrorActionPreference = 'Continue'

# Nom et derniere partie de l'adresse IP (identiques a create_vms.ps1)
$vms = @(
    @{ Name = 'bastion'; Ip = 10 },
    @{ Name = 'pg01';    Ip = 11 },
    @{ Name = 'pg02';    Ip = 21 }
)
$problems = 0

function Show([bool]$Ok, [string]$Label, [string]$Detail) {
    if ($Ok) { $tag = '[ok]'; $color = 'Green' } else { $tag = '[KO]'; $color = 'Red'; $script:problems++ }
    Write-Host ("{0} {1} {2}" -f $tag, $Label, $Detail) -ForegroundColor $color
}

# --- Reseau de l'hote -------------------------------------------------------------
Write-Host "== Reseau de l'hote =="
$sw = Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue
if ($sw) { Show ($sw.SwitchType -eq 'Internal') "Commutateur '$SwitchName'" "type $($sw.SwitchType)" }
else     { Show $false "Commutateur '$SwitchName'" 'absent (lancer create_vms.ps1)' }

$gw = @(Get-NetIPAddress -IPAddress "$Subnet.1" -ErrorAction SilentlyContinue)
$gwNames = ($gw | ForEach-Object { $_.InterfaceAlias }) -join ', '
$expectedAlias = "vEthernet ($SwitchName)"
$gwOk = ($gw.Count -eq 1) -and ($gw[0].InterfaceAlias -eq $expectedAlias)
Show $gwOk "Passerelle $Subnet.1 sur l'hote" ("{0} interface(s) : {1} (attendu : {2})" -f $gw.Count, $gwNames, $expectedAlias)
if ((-not $gwOk) -and ($gw.Count -ge 1)) {
    Write-Host "     $Subnet.1 est portee par une autre carte que celle du commutateur '$SwitchName' (reste d'un essai precedent) : les VM ne joindront pas l'hote. Voir docs/installation_vm.md, Depannage SSH, cause 1." -ForegroundColor Yellow
}

$nats = @(Get-NetNat -ErrorAction SilentlyContinue | Where-Object { $_.InternalIPInterfaceAddressPrefix -eq "$Subnet.0/24" })
$natNames = ($nats | ForEach-Object { $_.Name }) -join ', '
Show ($nats.Count -eq 1) "NAT $Subnet.0/24" ("{0} trouve(s) : {1}" -f $nats.Count, $natNames)

# --- VM Hyper-V ---------------------------------------------------------------------
Write-Host ""
Write-Host "== VM Hyper-V =="
foreach ($v in $vms) {
    $vm = Get-VM -Name $v.Name -ErrorAction SilentlyContinue
    if (-not $vm) { Show $false $v.Name 'VM absente'; continue }
    $nic = @(Get-VMNetworkAdapter -VMName $v.Name)[0]
    $guestIps = ($nic.IPAddresses | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' }) -join ', '
    if (-not $guestIps) { $guestIps = 'aucune (VM arretee ou services d''integration pas encore prets)' }
    $ok = ($vm.State -eq 'Running') -and ($nic.SwitchName -eq $SwitchName)
    Show $ok $v.Name ("etat {0}, commutateur '{1}', IP vue par Hyper-V : {2}" -f $vm.State, $nic.SwitchName, $guestIps)
}

# --- Acces reseau et SSH ------------------------------------------------------------------
Write-Host ""
Write-Host "== Acces reseau et SSH =="
$hasKeygen = [bool](Get-Command ssh-keygen -ErrorAction SilentlyContinue)
$hasSsh    = [bool](Get-Command ssh -ErrorAction SilentlyContinue)
foreach ($v in $vms) {
    $ip = "$Subnet.$($v.Ip)"

    $ping = Test-Connection -ComputerName $ip -Count 1 -Quiet -ErrorAction SilentlyContinue
    Show ([bool]$ping) "$($v.Name) ping $ip" ''

    $banner = $null
    $c = New-Object Net.Sockets.TcpClient
    try {
        if ($c.ConnectAsync($ip, 22).Wait(3000)) {
            $stream = $c.GetStream()
            $stream.ReadTimeout = 3000
            $buf = New-Object byte[] 255
            $n = $stream.Read($buf, 0, 255)
            $banner = ([Text.Encoding]::ASCII.GetString($buf, 0, $n)).Trim()
        }
    } catch { } finally { $c.Close() }
    if ($banner) { Show $true "$($v.Name) port 22" "banniere : $banner" }
    else         { Show $false "$($v.Name) port 22" 'pas de reponse SSH (VM arretee, installation inachevee, sshd absent ou mauvaise IP)' }

    if ($hasKeygen) {
        $known = & ssh-keygen -F $ip 2>$null
        if ($LASTEXITCODE -eq 0 -and $known) {
            Write-Host "     [i] known_hosts contient deja une cle pour $ip. Si ssh affiche 'REMOTE HOST IDENTIFICATION HAS CHANGED' (VM recreee) : ssh-keygen -R $ip" -ForegroundColor Yellow
        }
    }

    if ($TrySsh -and $banner -and $hasSsh) {
        # Les erreurs de ssh sont lues comme du texte (sinon PowerShell les affiche comme une exception).
        $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try { $out = (& ssh -o BatchMode=yes -o ConnectTimeout=5 "$AdminUser@$ip" hostname 2>&1 | ForEach-Object { "$_" }) -join ' ' }
        finally { $ErrorActionPreference = $old }
        $out = $out.Trim()
        if     ($out -match 'REMOTE HOST IDENTIFICATION HAS CHANGED') { $msg = "cle d'hote differente de known_hosts (VM recreee) : ssh-keygen -R $ip, puis ssh a la main" }
        elseif ($out -match 'Host key verification failed')          { $msg = "cle d'hote pas encore connue (normal a la 1re connexion) : lancer ssh $AdminUser@$ip a la main, verifier l'empreinte, repondre yes" }
        elseif ($out -match 'Permission denied')                      { $msg = 'sshd repond, authentification refusee sans mot de passe (normal sans cle SSH)' }
        else                                                          { $msg = $out }
        Write-Host ("     ssh {0}@{1} -> {2}" -f $AdminUser, $ip, $msg)
    }
}

Write-Host ""
if ($problems -eq 0) { Write-Host "Tout est ok cote Windows. Etape suivante : ssh $AdminUser@$Subnet.10 puis sudo cloud-init status --wait --long (Ubuntu)." -ForegroundColor Green }
else { Write-Host "$problems point(s) en erreur : voir docs/installation_vm.md, section 'Depannage SSH'." -ForegroundColor Red }
