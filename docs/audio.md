# Son partagé sur le réseau maillé (phase 42)

Tout appareil CCS qui sait jouer du son est une **sortie audio** pour les autres ; tout appareil
qui sait capter le sien est une **source**. On envoie le son dans tous les sens : iPhone →
pc-bureau, pc-bureau → Pixel, Pixel → iPhone…

Le serveur CCS (pont de l'utilisateur sur le VPS) ne fait que la mise en relation. Le son passe en
UDP direct entre les adresses du réseau maillé (100.64.x).

## 1. Annonce

Pas de multicast sur Tailscale, donc pas de mDNS : chaque appareil annonce au pont du serveur ce
qu'il sait faire, **toutes les 30 s** tant que CCS est ouvert (et, sur Linux, tant que le démon
tourne). Le pont l'oublie **90 s** après sa dernière annonce.

```json
→ {"method": "audio.announce", "params": {
     "device": "iphone",            // nom de l'appareil sur le réseau maillé (Tailscale)
     "label": "iPhone de Charles",  // nom affiché (facultatif)
     "ip": "100.64.0.4",            // son adresse maillée (interface 100.64.0.0/10)
     "port": 4010,                  // port UDP où il écoute quand il reçoit (défaut 4010)
     "play": true,                  // sait jouer un flux reçu
     "capture": true,               // sait capter son propre son et l'émettre
     "system": "ios"}}              // linux | android | ios | macos | windows | web | autre
← {"ok": true, "every": 30, "forget_after": 90, "streams": [ …flux en cours qui le concernent… ]}
```

`device` : lettres, chiffres, `.`, `_`, `-` (63 au plus). Pour le trouver, un appareil prend son
adresse 100.64.x (interfaces réseau : `tun0`/`tailscale0` sur Android et Linux, `utun*` sur iOS),
appelle `network.status` et garde le nom du pair (`self` ou `peers[]`) qui a cette adresse ; à
défaut, un nom tiré du modèle (`pixel`, `iphone`).

`audio.forget {device}` : l'appareil part (CCS fermé, son désactivé) ; ses flux s'arrêtent.

## 2. Liste

```json
→ {"method": "audio.list"}
← {"devices": [{"device", "label", "ip", "port", "play", "capture", "system", "age"}, …],
   "streams": [{"stream": "a3", "source": "pc-bureau", "target": "iphone", "started": 1764…}],
   "codec": {"codec": "opus", "rate": 48000, "channels": 2, "frame_ms": 10, "payload": 96},
   "every": 30}
```

Une **sortie** = un appareil `play: true` ; une **source** = `capture: true`.

## 3. Envoi

`audio.send {source, target}` (appelable depuis n'importe quel appareil : le bureau peut envoyer
le son de l'iPhone vers le Pixel). Le pont pousse l'événement `audio` à **tous** les appareils de
l'utilisateur ; chacun ne garde que ceux dont `device` est son propre nom :

1. pour la cible :
   `{"action": "receive", "device": "<cible>", "stream", "source", "target", "from", "from_label", "from_ip", "port", codec…}`
   → se mettre à écouter en UDP sur `port` et jouer ce qui arrive ;
2. pour la source :
   `{"action": "emit", "device": "<source>", "stream", "source", "target", "to", "to_label", "ip", "port", codec…}`
   → capter son son et l'émettre vers `ip:port`.

Réponse : `{"stream", "ip", "port", codec…}`. Une sortie ne joue qu'un flux à la fois, une source
n'émet qu'un flux : un nouvel envoi qui les touche arrête l'ancien (`stop`, raison `remplacé`).

**Sources qui demandent un accord à chaque départ** (Android : MediaProjection ; iPhone :
diffusion ReplayKit lancée par l'utilisateur) : l'envoi se lance **sur le téléphone même** (écran
« Son » → « Envoyer le son de ce téléphone vers… »). Le téléphone demande l'accord, appelle
`audio.send {source: lui, target}` puis émet dès l'événement `emit` (ou dès la réponse). Un
`emit` reçu sans accord en cours (envoi lancé depuis un autre appareil) : notification « Touchez
pour envoyer le son vers X » qui ouvre la demande d'accord.

`audio.stop {stream}` ou `audio.stop {device}` → événement
`{"action": "stop", "stream", "devices": [source, cible], "source", "target", "reason"}` :
la source cesse d'émettre, la cible cesse d'écouter.

## 4. Transport : RTP/Opus (RFC 7587)

- UDP, de la source vers `ip:port` de la cible ; **un paquet RTP = une trame Opus de 10 ms**
  (les trames de 20 ms restent acceptées : le récepteur lit leur durée dans l'octet TOC d'Opus).
- 48 kHz, stéréo (le récepteur accepte aussi le mono : `channels` de l'en-tête Opus).
- En-tête RTP de 12 octets : `V=2, P=0, X=0, CC=0`, `M=0`, **PT=96**, numéro de séquence (16 bits,
  +1 par paquet, départ aléatoire), horodatage (32 bits, **+480 par trame** de 10 ms, +960 pour
  20 ms, départ aléatoire), SSRC aléatoire (32 bits). Charge utile : la trame Opus brute (pas d'Ogg).
- Débit Opus conseillé : 96 kb/s stéréo, trames de 10 ms, mode `restricted-lowdelay` (CELT seul)
  quand l'encodeur le permet (GStreamer). Apple (AudioConverter) et Android (MediaCodec) n'ont pas
  ce réglage ; l'encodeur Opus de MediaCodec reste à 20 ms (pas de réglage public de durée).
- Récepteur : **tampon de gigue adaptatif** (ordre par numéro de séquence, paquets en retard jetés,
  trou → masquage de perte du décodeur ou silence). Départ à **30 ms** ; +10 ms à chaque perte ou
  sous-alimentation (une fois par rafale, répit de 500 ms ; une pause de plus de 300 ms ne compte
  pas) ; −10 ms après **10 s** sans incident ; borné entre **20 et 150 ms**. Rien reçu pendant
  **10 s** : on arrête d'écouter (le pont enverra `stop` de toute façon).
- Retard attendu : 50 à 100 ms en direct ; bien plus par un relais Tailscale (DERP).

Valeurs par plateforme (constantes nommées dans le code) :

| | Émission | Réception |
|---|---|---|
| Linux (`ccs_app/audio.py`) | `FRAME_MS = 10`, `opusenc frame-size=10 audio-type=restricted-lowdelay`, petits tampons `pulsesrc` | `rtpjitterbuffer latency=40` (`LATENCY_MS`, réglable par `latency_ms`) |
| iPhone (`Rtp.swift`, `Son.swift`) | trames de 10 ms (AudioConverter) | session `setPreferredIOBufferDuration(0.005)`, `GigueAdaptative`, 20 ms d'avance de silence au départ |
| Android (`Audio.kt`, `LecteurRtp.kt`, `CaptureSon.kt`) | capture par blocs de 10 ms, tampon `AudioRecord` de 40 ms (`CAPTURE_MS`) ; trames de 20 ms (MediaCodec) | `AudioTrack` en `PERFORMANCE_MODE_LOW_LATENCY`, tampon max(minimum, 40 ms) (`PISTE_MS`), `GigueAdaptative` |

Compatible GStreamer côté Linux :

```sh
# recevoir
gst-launch-1.0 udpsrc port=4010 caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS,payload=96" \
  ! rtpjitterbuffer latency=40 ! rtpopusdepay ! opusdec plc=true ! audioconvert ! audioresample ! autoaudiosink
# émettre le son d'une sortie PipeWire
gst-launch-1.0 pulsesrc device=<sortie>.monitor ! audioconvert ! audioresample \
  ! audio/x-raw,rate=48000,channels=2 ! opusenc bitrate=96000 frame-size=10 audio-type=restricted-lowdelay \
  ! rtpopuspay pt=96 ! udpsink host=100.64.0.4 port=4010
```

## 5. Par système

| | Jouer (sortie) | Capter (source) |
|---|---|---|
| Linux | GStreamer → sortie PipeWire par défaut | moniteur d'une sortie PipeWire ; chaque appareil distant est une **sortie virtuelle** (« iPhone de Charles ») : l'utiliser dans les réglages du son lance l'envoi |
| Android | service au premier plan, MediaCodec (décodeur Opus) → AudioTrack | Android 10+ : AudioPlaybackCapture (accord MediaProjection), MediaCodec (encodeur Opus) ; certaines applis interdisent la capture |
| iPhone | lecture en arrière-plan (`UIBackgroundModes: audio`), AudioConverter (Opus) → AVAudioEngine ; « Rester à l'écoute » (voir plus bas) | extension de diffusion ReplayKit (centre de contrôle) ; contenus protégés (Apple Music, Netflix…) muets |
| macOS | même agent (`ccs audio agent`), GStreamer → `autoaudiosink` | périphérique de bouclage (BlackHole) donné dans `capture_device` de `audio.toml` |
| Windows | même agent, GStreamer → `autoaudiosink` | `wasapi2src loopback=true` (son de la sortie par défaut) |
| Web | — (liste et télécommande seulement) | — |

iPhone, **« Rester à l'écoute »** (écran Son, réglage gardé, désactivé par défaut) : iOS suspend
l'appli en arrière-plan, qui rate alors l'ordre `receive` du pont. Activé, le récepteur UDP reste
ouvert sur le port annoncé et le lecteur joue du silence (la session audio active garde l'appli
éveillée) ; tout paquet RTP reçu, de n'importe quelle source, est joué tout de suite, sans arrêt
après 10 s de silence. L'appli continue d'annoncer toutes les 30 s et de suivre les événements
(nom de la source, `stop`) ; l'écoute tombée est rouverte à l'annonce suivante. Interruption
(appel, autre appli audio) : lecture reprise à la fin. Coût : un peu de batterie.

Linux : `ccs audio list`, `ccs audio send <source> <sortie>`, `ccs audio stop`,
`ccs audio receive` (au premier plan, pour essayer). Le démon CCS annonce la machine et crée les
sorties virtuelles tout seul quand le réglage « son partagé » est actif.
