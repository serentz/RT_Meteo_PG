<#
.SYNOPSIS
  Cree le reseau et les 3 VM Hyper-V du POC RT_Meteo_PG, OS installes automatiquement.

.DESCRIPTION
  - commutateur interne + NAT (192.168.50.0/24, passerelle .1 = le PC hote) ;
  - 3 VM generation 2, toutes Ubuntu Server (autoinstall) : bastion (scrutateur + Grafana), pg01 (stockage),
    pg02 (instance PostgreSQL surveillee) ;
  - chaque VM recoit un petit disque "graine" (CIDATA) avec sa configuration : IP fixe, nom,
    utilisateur, SSH, disque entier, /etc/hosts ;
  - le script attend la fin des installations (les VM s'eteignent seules), retire ISO et disques graines,
    redemarre les VM et attend que SSH reponde.
  Rejouable : -Destroy supprime les VM du POC, leurs disques et le reseau (commutateur, carte vEthernet, NAT) pour recommencer de zero ; -Only limite a certaines VM
  (ex. -Only pg02 pour recreer seulement l'instance surveillee).

ATTENTION
  PowerShell ouvert en administrateur. Fonctionnalite Windows "Hyper-V" requise.

.PARAMETER UbuntuIso
  Chemin complet du fichier .iso d'Ubuntu Server (pas un dossier). Obligatoire sauf avec -Destroy.
.PARAMETER VmRoot
  Dossier des VM et de leurs disques. Defaut : I:\POC\HyperV.
.PARAMETER SwitchName
  Nom du commutateur interne cree pour le POC.
.PARAMETER Subnet
  Trois premiers octets du reseau /24 (passerelle .1 = le PC). Defaut : 192.168.50.
.PARAMETER AdminUser
  Utilisateur cree sur toutes les VM. Defaut : admin01. Le mot de passe est demande a l'execution (ou -AdminPassword).
.PARAMETER AdminPassword
  Mot de passe (SecureString). Sinon il est demande a la saisie.
.PARAMETER SshPublicKeyFile
  Cle publique SSH a installer. Defaut : ~\.ssh\id_ed25519.pub ou id_rsa.pub s'ils existent.
.PARAMETER Keyboard
  Disposition du clavier. Defaut : fr.
.PARAMETER InstallTimeoutMin
  Delai maximal d'installation, en minutes. Defaut : 60.
.PARAMETER Only
  Ne traiter que ces VM (noms Hyper-V), ex. -Only <nom>.
.PARAMETER Destroy
  Supprime les VM du POC, leurs disques et le reseau cree par le script : NAT, commutateur interne et carte vEthernet de l'hote (confirmation OUI demandee). Avec -Only, le reseau est conserve.
.PARAMETER NoConsole
  N'ouvre pas les consoles des VM pendant l'installation.
.PARAMETER Help
  Affiche cette aide et quitte (ne demande pas les droits administrateur). Equivalent : Get-Help .\create_vms.ps1 -Detailed

.EXAMPLE
  .\create_vms.ps1 -UbuntuIso "K:\ShareLinux\Image ISO\ubuntu-24.04.5-live-server-amd64.iso"
  Cree le reseau et les 3 VM, puis installe Ubuntu sans intervention.

.EXAMPLE
  .\create_vms.ps1 -Destroy
  Supprime les 3 VM, leurs disques et le reseau cree par le script (commutateur, carte vEthernet, NAT). Avec -Only, le reseau est conserve.
#>
[CmdletBinding()]
param(
    [string]$UbuntuIso,
    [string]$VmRoot     = 'I:\POC\HyperV',
    [string]$SwitchName = 'compa-net',
    [string]$Subnet     = '192.168.50',       # trois premiers octets, masque /24
    [string]$AdminUser  = 'admin01',          # utilisateur cree sur les 3 VM
    [securestring]$AdminPassword,             # sinon demande a la saisie
    [string]$SshPublicKeyFile,                # defaut : ~\.ssh\id_ed25519.pub ou id_rsa.pub s'ils existent
    [string]$Keyboard   = 'fr',
    [int]$InstallTimeoutMin = 60,
    [string[]]$Only,                          # ne traiter que ces VM, ex. -Only pg02
    [switch]$Destroy,                         # supprime les VM du POC et, sans -Only, leur reseau
    [switch]$NoConsole,                       # n'ouvre pas les consoles
    [Alias('h')][switch]$Help                 # affiche l'aide et quitte
)

$ErrorActionPreference = 'Stop'

# Aide : avant tout controle, pour fonctionner meme sans droits administrateur
if ($Help) {
    Get-Help -Name $PSCommandPath -Detailed
    return
}
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Ce script doit etre lance dans un PowerShell ouvert en administrateur (aide : .\create_vms.ps1 -Help)."
}
$Here = $PSScriptRoot

# Nom, OS, vCPU, RAM (Go), disque (Go), derniere partie de l'adresse IP
$vms = @(
    @{ Name = 'bastion'; Os = 'ubuntu'; Cpu = 2; MemGB = 4; DiskGB = 30; Ip = 10 },
    @{ Name = 'pg01';    Os = 'ubuntu'; Cpu = 2; MemGB = 4; DiskGB = 30; Ip = 11 },
    @{ Name = 'pg02';    Os = 'ubuntu'; Cpu = 2; MemGB = 4; DiskGB = 30; Ip = 21 }
 )

$allVms = $vms      # /etc/hosts contient toujours les 3 VM
if ($Only) {
    $unknown = $Only | Where-Object { $allVms.Name -notcontains $_ }
    if ($unknown) { throw "-Only : VM inconnue(s) $($unknown -join ', '). Valeurs possibles : $($allVms.Name -join ', ')" }
    $vms = @($allVms | Where-Object { $Only -contains $_.Name })
}

if (-not (Get-Command New-VM -ErrorAction SilentlyContinue)) {
    throw "Module Hyper-V absent. Activer la fonctionnalite Windows Hyper-V (Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All), redemarrer, relancer."
}

# --- Mode -Destroy ---------------------------------------------------------------
if ($Destroy) {
    Write-Warning "Va supprimer les VM $($vms.Name -join ', ') et leurs disques dans $VmRoot."
    if ((Read-Host "Taper OUI pour confirmer") -ne 'OUI') { Write-Host "Annule."; return }
    foreach ($v in $vms) {
        $vm = Get-VM -Name $v.Name -ErrorAction SilentlyContinue
        if ($vm) {
            if ($vm.State -ne 'Off') { Stop-VM -Name $v.Name -TurnOff -Force }
            Remove-VM -Name $v.Name -Force
            Write-Host "[-] VM $($v.Name) supprimee"
        }
        $dir = Join-Path $VmRoot $v.Name
        if (Test-Path -LiteralPath $dir) { Remove-Item -LiteralPath $dir -Recurse -Force }
    }
    if ($Only) {
        Write-Host "Reseau '$SwitchName' conserve (-Only : les autres VM l'utilisent). Relancer le script sans -Destroy pour recreer les VM."
    } else {
        # Reseau cree par le script : NAT puis commutateur. Supprimer un commutateur interne retire aussi sa carte
        # "vEthernet ($SwitchName)" de l'hote (sinon elles s'accumulent a chaque projet recree).
        foreach ($n in @(Get-NetNat -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq $SwitchName -or $_.InternalIPInterfaceAddressPrefix -eq "$Subnet.0/24" })) {
            Remove-NetNat -Name $n.Name -Confirm:$false
            Write-Host "[-] NAT $($n.Name) supprime"
        }
        $sw = Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue
        if ($sw -and $sw.SwitchType -eq 'Internal') {
            Remove-VMSwitch -Name $SwitchName -Force
            Write-Host "[-] Commutateur '$SwitchName' et carte 'vEthernet ($SwitchName)' supprimes"
        } elseif ($sw) {
            Write-Host "[i] Commutateur '$SwitchName' (type $($sw.SwitchType)) conserve : il n'a pas ete cree par ce script ou relie une carte physique."
        }
        Write-Host "Relancer le script sans -Destroy pour recreer le reseau et les VM."
    }
    return
}

# --- Controles -------------------------------------------------------------------
$needed = @()
if ($vms | Where-Object { $_.Os -eq 'ubuntu' }) { $needed += ,@('UbuntuIso', $UbuntuIso) }
foreach ($p in $needed) {
    if (-not $p[1] -or -not (Test-Path -LiteralPath $p[1] -PathType Leaf)) {
        throw "-$($p[0]) : il faut le chemin complet d'un fichier .iso existant (pas d'un dossier)."
    }
}
$existing = $vms | Where-Object { Get-VM -Name $_.Name -ErrorAction SilentlyContinue }
if ($existing) {
    throw "VM deja presentes : $($existing.Name -join ', '). Relancer avec -Destroy pour tout supprimer et recommencer."
}

# Mot de passe
if (-not $AdminPassword) {
    $s1 = Read-Host "Mot de passe de '$AdminUser' sur les 3 VM (8 caracteres min.)" -AsSecureString
    $s2 = Read-Host "Confirmer le mot de passe" -AsSecureString
    $plain1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s1))
    $plain2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s2))
    if ($plain1 -ne $plain2) { throw "Les deux mots de passe different." }
    $Password = $plain1
} else {
    $Password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($AdminPassword))
}
# Caracteres autorises : evitent tout probleme de guillemets dans YAML
if ($Password -notmatch '^[A-Za-z0-9!@#%^*_+=.,:;/?-]{8,}$') {
    throw "Mot de passe : 8 caracteres minimum, parmi lettres, chiffres et !@#%^*_+=.,:;/?- (pas d'espace, guillemet, \ ni `$)."
}
if ($AdminUser -notmatch '^[a-z][a-z0-9_-]{0,30}$') { throw "-AdminUser : minuscules, chiffres, - et _ (commence par une lettre)." }

# Cle SSH publique (facultative)
if (-not $SshPublicKeyFile) {
    foreach ($c in @('id_ed25519.pub', 'id_rsa.pub')) {
        $f = Join-Path $HOME ".ssh\$c"
        if (Test-Path -LiteralPath $f) { $SshPublicKeyFile = $f; break }
    }
}
$sshKey = $null
if ($SshPublicKeyFile -and (Test-Path -LiteralPath $SshPublicKeyFile)) {
    $sshKey = (Get-Content -LiteralPath $SshPublicKeyFile -TotalCount 1).Trim()
    if ($sshKey -notmatch '^(ssh-[a-z0-9]+|ecdsa-[a-z0-9-]+) [A-Za-z0-9+/=]+( .*)?$' -or $sshKey -match '["''\\]') {
        throw "Cle publique illisible dans $SshPublicKeyFile"
    }
    Write-Host "[i] Cle SSH publique ajoutee : $SshPublicKeyFile"
} else {
    Write-Host "[i] Pas de cle SSH publique : connexion par mot de passe uniquement."
}

# --- Reseau : commutateur interne + NAT --------------------------------------------
if (-not (Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue)) {
    Write-Host "[+] Commutateur interne '$SwitchName'"
    New-VMSwitch -Name $SwitchName -SwitchType Internal | Out-Null
}
$alias = "vEthernet ($SwitchName)"
if (-not (Get-NetIPAddress -InterfaceAlias $alias -IPAddress "$Subnet.1" -ErrorAction SilentlyContinue)) {
    Write-Host "[+] Adresse $Subnet.1/24 sur $alias (passerelle des VM)"
    New-NetIPAddress -InterfaceAlias $alias -IPAddress "$Subnet.1" -PrefixLength 24 | Out-Null
}
$nat = Get-NetNat -ErrorAction SilentlyContinue
if (-not ($nat | Where-Object { $_.InternalIPInterfaceAddressPrefix -eq "$Subnet.0/24" })) {
    Write-Host "[+] NAT $Subnet.0/24 (acces Internet des VM)"
    New-NetNat -Name $SwitchName -InternalIPInterfaceAddressPrefix "$Subnet.0/24" | Out-Null
}

# --- Disque graine (volume FAT32 avec la configuration d'installation) ---------------
$utf8 = New-Object System.Text.UTF8Encoding($false)
function New-SeedDisk {
    param([string]$Path, [string]$Label, [hashtable]$Files)
    New-VHD -Path $Path -SizeBytes 128MB -Dynamic | Out-Null
    $number = (Mount-VHD -Path $Path -Passthru | Get-Disk).Number
    try {
        Initialize-Disk -Number $number -PartitionStyle MBR
        $part = New-Partition -DiskNumber $number -UseMaximumSize -AssignDriveLetter
        $vol = Format-Volume -Partition $part -FileSystem FAT32 -NewFileSystemLabel $Label -Force -Confirm:$false
        $root = "$($vol.DriveLetter):\"
        foreach ($name in $Files.Keys) {
            [IO.File]::WriteAllText((Join-Path $root $name), ($Files[$name] -replace "`r`n", "`n"), $utf8)
        }
    } finally {
        Dismount-VHD -Path $Path
    }
}

function Expand-Template {
    param([string]$TemplateFile, [hashtable]$Values)
    $t = Get-Content -LiteralPath (Join-Path $Here "templates\$TemplateFile") -Raw
    foreach ($k in $Values.Keys) { $t = $t.Replace("{{$k}}", [string]$Values[$k]) }
    return $t
}

$hostsPlain = ($allVms | Sort-Object { $_.Ip } | ForEach-Object { "{0}.{1}  {2}" -f $Subnet, $_.Ip, $_.Name }) -join "`n"
$hostsYaml  = ($hostsPlain -split "`n" | ForEach-Object { "          $_" }) -join "`n"

# --- Creation des VM --------------------------------------------------------------------
foreach ($v in $vms) {
    $name = $v.Name
    $dir  = Join-Path $VmRoot $name
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Write-Host "[+] VM $name ($($v.Os), $($v.Cpu) vCPU, $($v.MemGB) Go, disque $($v.DiskGB) Go, $Subnet.$($v.Ip))"

    New-VM -Name $name -Generation 2 -Path $VmRoot `
        -MemoryStartupBytes ([uint64]$v.MemGB * 1GB) `
        -NewVHDPath (Join-Path $dir "$name.vhdx") -NewVHDSizeBytes ([uint64]$v.DiskGB * 1GB) `
        -SwitchName $SwitchName | Out-Null
    Set-VMProcessor -VMName $name -Count $v.Cpu
    Set-VMMemory -VMName $name -DynamicMemoryEnabled $false
    Set-VM -Name $name -AutomaticCheckpointsEnabled $false

    # Configuration d'installation
    $iso = $UbuntuIso
    $values = @{
        NAME = $name; IP = "$Subnet.$($v.Ip)"; GATEWAY = "$Subnet.1"; USER = $AdminUser
        PASSWORD = $Password; KEYBOARD = $Keyboard
    }
    $seed = Join-Path $dir "seed-$name.vhdx"
    # ssh_authorized_keys ne doit jamais etre une liste vide : la ligne est omise sans cle
    $values.SSHKEYS = if ($sshKey) { "ssh_authorized_keys: [""$sshKey""]" } else { "" }
    $values.HOSTS   = $hostsYaml
    New-SeedDisk -Path $seed -Label 'CIDATA' -Files @{
        'user-data' = (Expand-Template 'ubuntu-user-data.tpl' $values)
        'meta-data' = "instance-id: $name-install`nlocal-hostname: $name`n"
    }
    Add-VMHardDiskDrive -VMName $name -Path $seed -ControllerType SCSI -ControllerNumber 0 -ControllerLocation 1

    # ISO, Secure Boot Linux, ordre de demarrage : disque systeme puis DVD
    # (disque vide au premier demarrage -> l'ISO ; apres installation -> le disque, sans toucher a l'ISO)
    $dvd = Add-VMDvdDrive -VMName $name -Path $iso -Passthru
    $os  = Get-VMHardDiskDrive -VMName $name | Where-Object { $_.Path -like "*\$name.vhdx" }
    Set-VMFirmware -VMName $name -EnableSecureBoot On -SecureBootTemplate 'MicrosoftUEFICertificateAuthority' `
        -BootOrder $os, $dvd
}

# --- Installation automatique -------------------------------------------------------------
Start-VM -Name $vms.Name
if (-not $NoConsole) { foreach ($v in $vms) { Start-Process vmconnect.exe -ArgumentList 'localhost', $v.Name } }

Write-Host ""
Write-Host "Installation en cours dans les 3 VM (10 a 20 minutes, en parallele)."
Write-Host "  - Ubuntu (bastion, pg01, pg02) : si une console demande 'Continue with autoinstall?', taper  yes  puis Entree."
Write-Host "Les VM s'eteignent toutes seules a la fin : ne rien faire d'autre."

$pending  = [System.Collections.ArrayList]@($vms.Name)
$deadline = (Get-Date).AddMinutes($InstallTimeoutMin)
while ($pending.Count -gt 0) {
    if ((Get-Date) -gt $deadline) {
        throw "Delai de $InstallTimeoutMin min depasse, VM encore en cours : $($pending -join ', '). Verifier leurs consoles."
    }
    Start-Sleep -Seconds 20
    foreach ($n in @($pending)) {
        if ((Get-VM -Name $n).State -eq 'Off') {
            Write-Host "[ok] $n : installation terminee"
            $pending.Remove($n)
        }
    }
}

# --- Nettoyage : ISO et disques graines (ils contiennent le mot de passe) --------------------
foreach ($v in $vms) {
    $n = $v.Name
    Get-VMDvdDrive -VMName $n | Set-VMDvdDrive -Path $null
    Get-VMHardDiskDrive -VMName $n | Where-Object { $_.Path -like "*seed-$n.vhdx" } | Remove-VMHardDiskDrive
    Remove-Item -LiteralPath (Join-Path (Join-Path $VmRoot $n) "seed-$n.vhdx") -Force -ErrorAction SilentlyContinue
}

# --- Premier demarrage et attente de SSH ---------------------------------------------------------
Start-VM -Name $vms.Name
Write-Host "[i] VM redemarrees, attente de SSH..."
function Test-Port($ip, $port) {
    $c = New-Object Net.Sockets.TcpClient
    try { return $c.ConnectAsync($ip, $port).Wait(1500) } catch { return $false } finally { $c.Close() }
}
$deadline = (Get-Date).AddMinutes(10)
$up = @{}
while ($up.Count -lt $vms.Count -and (Get-Date) -lt $deadline) {
    foreach ($v in $vms) {
        if (-not $up.ContainsKey($v.Name) -and (Test-Port "$Subnet.$($v.Ip)" 22)) { $up[$v.Name] = $true }
    }
    if ($up.Count -lt $vms.Count) { Start-Sleep -Seconds 10 }
}

Write-Host ""
foreach ($v in ($vms | Sort-Object { $_.Ip })) {
    $state = if ($up.ContainsKey($v.Name)) { 'SSH ok' } else { 'SSH ne repond pas (voir la console)' }
    Write-Host ("  {0,-8} {1}.{2,-3} ssh {3}@{1}.{2}   {4}" -f $v.Name, $Subnet, $v.Ip, $AdminUser, $state)
}
Write-Host ""
Write-Host "Verification SSH et reseau : .\infra\hyperv\check_vms.ps1 (lecture seule)."
Write-Host "Etape suivante : docs/installation_vm.md section 'Suite' (PostgreSQL sur pg01 et pg02)."
