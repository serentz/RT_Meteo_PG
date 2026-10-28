# Installation des trois VM

## Prérequis

PC Windows avec Hyper-V disponible et activé, PowerShell administrateur, au moins 12 Go de RAM libres pour les invités en plus de Windows, espace disque suffisant sur I:. Les ISO doivent être les médias complets Ubuntu Server 24.04 LTS, téléchargé auprès de l'éditeur et contrôlé par sa somme de contrôle. L'ISO n'est pas incluse. Les trois VM utilisent le même ISO.

Le réseau est 192.168.50.0/24 avec passerelle 192.168.50.1 (le PC hôte), sur le commutateur interne `compa-net` (nom hérité du projet `comparaison_ase`, modifiable avec `-SwitchName`). Vérifier qu'il n'entre pas en conflit avec LAN, VPN ou réseau Hyper-V existant. Le script réutilise un commutateur, une adresse et un NAT déjà présents mais ne résout aucun conflit. En particulier, un reste d'un essai précédent (commutateur `rt-meteo-ase-net`, ancien NAT, ancien environnement `comparaison_ase` encore démarré) qui utilise la même plage 192.168.50.0/24 fait échouer SSH : voir « Dépannage SSH ».

**Si les VM du projet RT_Meteo_ASE existent encore** (`bastion`, `pg01`, `ase01`), elles portent les mêmes noms et les mêmes adresses : les supprimer d'abord avec le `-Destroy` de ce projet-là (ou en arrêter l'usage), car deux environnements ne peuvent pas coexister sur 192.168.50.0/24.

Les noms `bastion`, `pg01`, `pg02` doivent être libres : le script s'arrête si une VM de ce nom existe déjà. Il ne contrôle pas l'existence des dossiers. `-Destroy` supprime les VM par leur nom : ne pas le lancer si des VM d'un autre projet portent les mêmes noms.

## Lancement

Depuis PowerShell administrateur :

```powershell
Set-Location 'I:\POC\RT_Meteo_PG'
Get-Help .\infra\hyperv\create_vms.ps1 -Detailed
# Adapter le chemin à l'ISO réellement présente.
.\infra\hyperv\create_vms.ps1 -UbuntuIso 'K:\ShareLinux\Image ISO\ubuntu-server.iso'
```

Le mot de passe est demandé à l'exécution. Ne pas le saisir en clair dans une commande enregistrée. Une clé publique SSH locale est détectée si présente dans le profil utilisateur qui exécute PowerShell. Les VM et disques sont créés dans `I:\POC\HyperV` (paramètre `-VmRoot`), hors du répertoire Git.

Ce script automatise la configuration et l'installation après démarrage de l'installateur, mais n'édite pas les ISO :

- Ubuntu : confirmer `yes` si l'installateur le demande. Si nécessaire, ajouter `autoinstall` à la ligne du noyau via le menu GRUB.

Laisser les consoles ouvertes pour suivre l'installation. Un délai dépassé n'autorise aucune suppression automatique. Sur échec, vérifier les consoles ; les graines peuvent contenir le mot de passe en clair et doivent rester dans un dossier accessible uniquement aux administrateurs. Après succès, elles sont détachées puis supprimées.

Le disque graine (volume `CIDATA`) est attaché au contrôleur SCSI à l'emplacement 1. Le modèle efface le disque système de la VM. Le modèle Ubuntu n'active aucun pare-feu.

## Validation Windows et invités

Le script attend l'extinction de chaque VM (fin d'installation), retire les ISO et les graines, redémarre les invités et attend leur port TCP 22. Il n'existe pas de marqueur de succès : une VM éteinte n'est pas la preuve d'une installation réussie, et l'ouverture du port 22 ne vérifie ni l'authentification ni l'exécution complète de cloud-init.

Premier contrôle, en lecture seule, depuis PowerShell sur l'hôte :

```powershell
.\infra\hyperv\check_vms.ps1
.\infra\hyperv\check_vms.ps1 -TrySsh   # ajoute un essai ssh sans mot de passe
```

Il vérifie le commutateur, la passerelle 192.168.50.1 (doublon éventuel), le NAT, l'état des VM, le ping, le port 22 et la bannière SSH de chaque VM. Puis, à la main :

```powershell
Get-VM -Name bastion,pg01,pg02 | Select-Object Name,State,MemoryAssigned
ssh admin01@192.168.50.10
ssh admin01@192.168.50.11
ssh admin01@192.168.50.21
```

Une fois connecté à une VM, on tape ses commandes dans son terminal ; `exit` ramène à PowerShell. Sur chaque VM, exécuter `sudo cloud-init status --wait --long`, puis vérifier `hostname`, `ip -br address`, `ip route`, `getent hosts pg01 pg02 bastion`.

Le compte est membre de sudo et utilise son mot de passe pour sudo. Conserver la vérification des clés d'hôte SSH. Une recréation change ces clés : vérifier la nouvelle empreinte en console avant de mettre à jour known_hosts.

## Dépannage SSH

Causes les plus probables quand `ssh admin01@192.168.50.x` ne fonctionne pas, de la plus fréquente à la plus rare :

1. **Doublon de passerelle sur l'hôte.** Un essai précédent a laissé une autre carte `vEthernet (...)` (par exemple `rt-meteo-ase-net`) qui porte déjà 192.168.50.1 et un NAT sur 192.168.50.0/24. Le script voit le NAT existant, ne crée rien, et le trafic part sur la mauvaise carte. `check_vms.ps1` signale ce cas ; sinon : `Get-NetIPAddress -IPAddress 192.168.50.1`, `Get-NetNat`, `Get-VMSwitch`. Retirer ensuite le commutateur et le NAT en trop, après avoir vérifié qu'aucune VM n'y est connectée (`Get-VMNetworkAdapter -All | Where-Object SwitchName -eq 'rt-meteo-ase-net'`) : `Remove-NetNat -Name <nom> -Confirm:$false` puis `Remove-VMSwitch -Name <nom> -Force` (supprimer un commutateur interne retire aussi sa carte `vEthernet` et l'adresse qu'elle porte). `create_vms.ps1` recrée ensuite le commutateur, l'adresse et le NAT.
2. **Ancienne clé d'hôte.** Les VM recréées gardent les mêmes IP mais changent de clés : ssh refuse avec `REMOTE HOST IDENTIFICATION HAS CHANGED`. Vérifier la nouvelle empreinte en console, puis `ssh-keygen -R 192.168.50.10` (idem .11 et .21).
3. **Une autre VM répond sur la même IP** (ancien environnement `comparaison_ase`, projet RT_Meteo_ASE ou essai précédent encore démarré) : `Get-VM | Select-Object Name,State` et `Get-VMNetworkAdapter -All | Select-Object VMName,SwitchName,IPAddresses`.
4. **Installation inachevée.** Le port 22 est fermé tant que l'installateur tourne ou si la VM a redémarré sur l'ISO. Regarder la console de la VM. Sur Ubuntu, `cloud-init status --wait --long` après connexion console.
5. **Nom de carte.** Le modèle Ubuntu suppose `eth0`. Si la carte porte un autre nom, l'IP statique n'est pas appliquée : en console, `ip -br address` puis `ls /sys/class/net`.
6. **Authentification.** Le port 22 répond mais `Permission denied` : vérifier le mot de passe saisi (caractères autorisés listés dans le script) et, si une clé publique était détectée, qu'elle est bien celle de l'agent SSH utilisé.

7. **Pilote réseau d'un autre produit de virtualisation sur l'hôte (VirtualBox).** Symptôme observé : le ping des VM répond, mais toute connexion TCP depuis l'hôte (port 22, SSH) reste sans réponse jusqu'au délai dépassé, et une capture dans la VM (`tcpdump`) ne voit arriver aucune demande de connexion ; entre VM, SSH fonctionne. Le pilote `VirtualBox NDIS6 Bridged Networking Driver` était lié à toutes les cartes de l'hôte, `vEthernet` comprises (`Get-NetAdapterBinding -AllBindings | Where-Object { $_.Enabled -and $_.ComponentID -notlike 'ms_*' }`). Sur le PC de test, tout est rentré dans l'ordre après désinstallation de VirtualBox, `create_vms.ps1 -Destroy`, puis recréation des VM. Le pare-feu Windows, le pare-feu G DATA, la recréation du commutateur et la désactivation de ses extensions n'étaient pas en cause. Non vérifié : si la simple désactivation de la liaison VirtualBox, sans désinstaller le produit, suffit.

Un port 22 qui répond avec une bannière `SSH-2.0-OpenSSH...` prouve que sshd tourne et que le réseau est correct ; le reste relève de l'authentification.

## Recréation volontaire

```powershell
# Destructif : demande de confirmation OUI. Aucun contrôle de propriété : les VM sont supprimées par leur nom.
.\infra\hyperv\create_vms.ps1 -Destroy -Only pg02
# Puis recréer uniquement cette VM.
.\infra\hyperv\create_vms.ps1 -Only pg02 -UbuntuIso 'K:\ShareLinux\Image ISO\ubuntu-server.iso'
```

Avec `-Only`, seules les VM nommées et leurs dossiers dans `-VmRoot` sont supprimés ; le réseau est conservé car les autres VM l'utilisent. Sans `-Only`, `-Destroy` cible les trois VM, leurs dossiers, puis supprime aussi le NAT, le commutateur interne et la carte `vEthernet` de l'hôte : le réseau est recréé au lancement suivant. Les dossiers d'un essai précédent situés ailleurs que dans `-VmRoot` (par exemple `I:\POC\HyperV\RT_Meteo_ASE`, projet précédent) ne sont pas touchés et doivent être supprimés à la main une fois les VM correspondantes retirées.

## Suite

Installer PostgreSQL sur pg01 (stockage) et créer le schéma, PostgreSQL sur pg02 (instance surveillée), puis le scrutateur Python et Grafana sur bastion. pg02 ne reçoit ni agent ni extension : le scrutateur l'interroge à distance. Marche à suivre : [docs/scrutateur.md](scrutateur.md). Aucune de ces étapes applicatives n'est effectuée par le script Hyper-V.

## Références

- https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html
- https://canonical-subiquity.readthedocs-hosted.com/en/latest/explanation/cloudinit-autoinstall-interaction.html
