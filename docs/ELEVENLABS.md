# Voix off ElevenLabs

Gemini continue à rédiger et vérifier les scripts. ElevenLabs lit la narration française et renvoie l'audio ainsi que des repères temporels pour les sous-titres. Le montage décline la même voix dans les trois formats ; il ne génère pas trois voix facturées.

## Connexion initiale

Après avoir choisi votre abonnement ElevenLabs :

1. Créer une clé API dans votre compte, avec l'autorisation Text to Speech.
2. Choisir une voix adaptée au français, puis copier son Voice ID.
3. Renseigner uniquement dans le fichier `.env` local :

```dotenv
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
```

Ne pas enregistrer la clé dans config.yaml, GitHub ou un message de chat. `doctor` vérifie sa présence sans la révéler et sans générer d'audio :

```powershell
.\.venv\Scripts\python.exe -m pipelineia doctor
```

La voix choisie doit être accessible depuis le compte et le modèle sélectionnés. La présence locale d'une clé ne vérifie ni l'abonnement ni les crédits disponibles.

## Modèle et qualité

Le défaut `speech.provider: elevenlabs` utilise `eleven_flash_v2_5`, qui prend en charge le français et vise un coût réduit. Le format `mp3_44100_128` est ensuite converti localement en WAV pour le montage. Le PCM 44,1 kHz via API demande une offre supérieure ; il n'est pas requis ici.

Pour comparer une autre qualité, remplacer explicitement `speech.elevenlabs.model_id` par `eleven_multilingual_v2`. Cette modification peut consommer davantage de crédits et crée une nouvelle voix dans le cache. Les paramètres de stabilité, similarité et vitesse sont dans `speech.elevenlabs.voice_settings`. Le rendu ajuste ensuite la voix pour conserver exactement 60 secondes, sans couper la narration ; il refuse un changement de vitesse excessif.

[Modèles officiels](https://elevenlabs.io/docs/overview/models), [API avec repères temporels](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps).

## Consommation et reprise

L'appel de synthèse utilise l'abonnement et les crédits du compte. Le dépôt n'achète aucun abonnement, n'active pas de recharge et ne change pas de formule. Les limites et éventuels achats automatiques configurés dans le compte restent sous votre contrôle.

La narration déjà obtenue est conservée avec son empreinte. Une relance après un échec de montage réutilise l'audio vérifié si le texte, la voix et les paramètres sont identiques. Le changement du seul format vidéo ne déclenche pas une nouvelle synthèse. Les fichiers de cache sont dans le dossier de l'épisode, ignoré par Git ; les conserver pour éviter une nouvelle génération.

Une réponse réseau perdue peut correspondre à une génération déjà facturée. Le pipeline ne répète pas aveuglément cet appel : un état incertain bloque la génération et demande de vérifier l'historique ElevenLabs avant une intervention. Une réponse explicite de clé invalide ou de crédits épuisés est signalée sans basculer silencieusement vers une autre voix.

## Sous-titres

Les repères ElevenLabs sont utilisés uniquement s'ils correspondent au texte exact et au fichier audio. Leur tempo est adapté à celui du montage. `timing.json` indique alors `elevenlabs_character_alignment`. Si les repères sont absents ou invalides, le montage utilise le minutage estimé et l'indique dans ce fichier.

## Essai

Une fois la clé et le Voice ID renseignés, `run` produit une vraie narration ElevenLabs. Pour un premier exemple hors actualité, la commande suivante consomme aussi des crédits ElevenLabs :

```powershell
.\.venv\Scripts\python.exe -m pipelineia demo --quick
```

Pour vérifier le montage sans appel ElevenLabs, utiliser `demo --quick --silent`. Pour revenir volontairement à la voix locale gratuite, choisir `speech.provider: auto` dans config.yaml. Ce changement n'est jamais déclenché automatiquement par une panne ElevenLabs.
