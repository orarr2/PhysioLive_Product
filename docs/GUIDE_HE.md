<div dir="rtl" align="right">

# PhysioLive - מדריך מלא בעברית

מסמך זה סוקר את הפרויקט מקצה לקצה: מה הוא עושה, מה קיים בקוד, איך הרכיבים מדברים ביניהם, ואיך לפרוס אותו מחדש. הוא נועד גם לקורא שלא ראה מעולם את הריפו, וגם למי שרוצה לזכור פרטי מימוש שנקבעו במהלך הפיתוח. כל בלוקי הקוד ניתנים לקריאה משמאל לימין כמו קוד רגיל; טקסט הסבר נשאר מימין לשמאל.

## תוכן עניינים

1. [סקירה כללית](#סקירה-כללית)
2. [ארכיטקטורה במבט על](#ארכיטקטורה-במבט-על)
3. [מבנה הריפו](#מבנה-הריפו)
4. [Web App - הדפדפן](#web-app---הדפדפן)
5. [VM Backend - שרת FastAPI](#vm-backend---שרת-fastapi)
6. [הקורפוס המדעי](#הקורפוס-המדעי)
7. [פריסה מלאה](#פריסה-מלאה)
8. [אבטחה, JWT ו-Rate Limits](#אבטחה-jwt-ו-rate-limits)
9. [דוח מייל יומי](#דוח-מייל-יומי)
10. [פיתוח מקומי + מחברת ה-Python](#פיתוח-מקומי--מחברת-ה-python)
11. [מסלול הפיתוח](#מסלול-הפיתוח)

---

## סקירה כללית

PhysioLive הוא מאמן פיזיותרפיה בזמן אמת שרץ בדפדפן של המטופל. מטרתו לספק חוויית תרגול בטוחה ומדויקת בלי צורך בהתקנת אפליקציה, ובלי שהמטופל יצטרך לשלוח וידאו לשום מקום. כל תמונות המצלמה נשארות במכשיר שלו; רק סיכומים מספריים קצרים של תוצאת התרגיל נשלחים לשרת הענן כדי לקבל משפט אימון חופשי מתוך מודל שפה.

מה שהאפליקציה עושה בפועל:

- מזהה 33 נקודות ציון של הגוף (MediaPipe Pose) ועד 42 נקודות ציון של האצבעות (MediaPipe Hand) בכל פריים של המצלמה.
- מחשבת זוויות מפרקים בזמן אמת (ברך, ירך, מרפק, כתף, שיפוע הגו).
- סופרת חזרות של תרגילים באמצעות מכונת מצבים דטרמיניסטית שמזהה מעבר בין `STANDING` ל-`BOTTOM` וחוזרת.
- מריצה חוקי פורם דטרמיניסטיים על כל חזרה (עומק, יישור ברך מעל הקרסול, שיפוע גו קדימה, ועוד).
- שולחת את פסיקת הרפ ל-VM שמושך עדות רלוונטית מ-ChromaDB ומזמין את `openai/gpt-oss-120b` דרך Groq להרכיב משפט אימון קליני אחד.
- מציגה את המשפט למטופל עם קישור למקור, ומעדכנת HUD חי (זווית ברך, אחוז עומק, שלב, מספר חזרה).
- בסוף session שולחת דוח מייל יומי מפורט מ-Gmail SMTP.

חמישה תרגילים נתמכים כרגע: `squat`, `lunge`, `glute_bridge`, `leg_raise`, `shoulder_abduction`.

---

## ארכיטקטורה במבט על

```
+--------------------------------------------------------+
|  Browser (device: phone / laptop / desktop)            |
|                                                        |
|  MediaPipe PoseLandmarker (33 body)                    |
|  MediaPipe HandLandmarker  (21 x 2 hand)               |
|  angles.js -> rep_counter.js -> rules.js               |
|  HUD live: phase, knee angle, depth %, form flash      |
|                                                        |
|  auth.js (JWT + Google + passphrase)                   |
|  coach_client.js  ---HTTPS---> Cloudflare Tunnel       |
|  report_client.js ---HTTPS---> Cloudflare Tunnel       |
+--------------------------------------------------------+
                          |
                          v
+--------------------------------------------------------+
|  Google Cloud e2-micro (Free Tier, 1 GB RAM)           |
|                                                        |
|  cloudflared (outbound tunnel)                         |
|  FastAPI (uvicorn) systemd service                     |
|                                                        |
|  api.py                                                |
|   * /health                                            |
|   * /auth/login  (passphrase -> JWT)                   |
|   * /auth/google (Google id_token -> JWT)              |
|   * /rag/query                                         |
|   * /coach/feedback                                    |
|   * /report/daily/send                                 |
|                                                        |
|  auth.py             (JWT HS256, bcrypt passphrase)    |
|  coach_llm.py        (Groq client + system prompt)     |
|  email_report.py     (Gmail SMTP + LLM opinion)        |
|                                                        |
|  ChromaDB + ONNX all-MiniLM-L6-v2  (evidence store)    |
|  slowapi (per-IP + per-user rate limits)               |
|  SQLite ledgers: JWT secret, sent reports              |
+--------------------------------------------------------+
              |                             |
              v                             v
+---------------------------+   +--------------------------+
|  Groq API                 |   |  Gmail SMTP              |
|  openai/gpt-oss-120b      |   |  projgithub@gmail.com    |
|  free tier (30 req/min)   |   |  daily summary emails    |
+---------------------------+   +--------------------------+
```

הכלל הכי חשוב בפרויקט: **וידאו גולמי לעולם לא עוזב את המכשיר**. ה-VM מקבל רק אובייקטים קטנים בעלי שדות כמו `exercise`, `verdict_level`, `verdict_text`, `metrics.knee_angle=115`. אין תמונות, אין frames, אין הקלטות.

---

## מבנה הריפו

```
PhysioLive_Product/
  physio_live.ipynb          מחברת שולחן העבודה (הרצה ב-Run All)
  requirements.txt           תלויות pip לשולחן העבודה
  src/
    app/                     קוד ליבה משותף
      pose_gate.py           גישה לפוזה (MediaPipe / YOLO)
      angles.py              חישוב זוויות מפרקים
      exercises/             קונפיגורציית תרגילים JSON
      rep_counter.py         מכונת מצבים לספירת חזרות
      form_rules.py          מנוע חוקי פורם דטרמיניסטי
      dashboard_server.py    שרת HTTP + MJPEG + JSON API
      session_log.py         SQLite של הסבשן
      rag/
        embedder.py          עטיפת all-MiniLM-L6-v2
        store.py             ChromaDB persistent store
        corpus.py            ingest של seed + PubMed
        query.py             retrieval + citation helper
        pubmed_queries.py    רשימת 24 שאילתות PubMed
      agents/
        coach.py             לקוח coach שולחני
        progress.py          יצוא PDF של סיכום סבשן
      tools/
        build_index.py       בונה את ChromaDB
        train_rep_classifier.py  אימון LightGBM (רלוונטי לעתיד)
    vm/                      שרת FastAPI שרץ ב-VM
      api.py                 כל ה-endpoints
      auth.py                JWT + Google + passphrase
      coach_llm.py           קריאה ל-Groq / Anthropic
      email_report.py        דוח מייל יומי
      requirements.txt       תלויות slim
      deploy/                setup.sh, systemd units, cloudflared
  webapp/                    מקור GitHub Pages
    index.html
    manifest.webmanifest     Add to Home Screen
    favicon.svg
    apple-touch-icon.svg
    tunnel-url.json          URL עדכני של Cloudflare tunnel
    assets/
      app.js                 חיווט מלא: views, camera, sign-in, HUD
      pose.js                MediaPipe Tasks Vision
      angles.js              חישוב זוויות (מירר של angles.py)
      rep_counter.js         מכונת מצבים (מירר של rep_counter.py)
      rules.js               חוקי פורם (מירר של form_rules.py)
      exercises.js           קונפיגורציית תרגילים
      coach_client.js        לקוח /coach/feedback
      report_client.js       לקוח /report/daily/send
      session.js             לוג session ב-localStorage
      auth.js                Google + passphrase + JWT
      config.js              קונפיג runtime + tunnel-url resolver
      style.css              עיצוב מלא
  corpus/                    קורפוס מדעי (topic-per-folder)
    README.md                מבנה + מתודולוגיה
    INDEX.md                 טבלת seed + פקודה למדידת PubMed
    CONTRIBUTING.md          איך מוסיפים chunk
    squat/     chunks.json + README.md
    knee/      chunks.json + README.md
    hip/       chunks.json + README.md
    shoulder/  chunks.json + README.md
    general/   chunks.json + README.md
  data/
    corpus_seed/             legacy seed (נטען לצד corpus/)
    reference_signatures/    חתימות זוויות פר תרגיל
    reference_videos/        וידאו הדגמה (מחוץ ל-git)
    models/                  משקולות ONNX (מחוץ ל-git)
    sessions/                SQLite של הסבשן שולחני (מחוץ ל-git)
    chroma/                  vector index (מחוץ ל-git)
  docs/
    GUIDE_HE.md              המסמך הזה
    rate-limits.md           מגבלות בקצה כל שכבה
    deployment.md            מדריך פריסה
  .github/workflows/
    pages.yml                פריסת GitHub Pages
```

---

## Web App - הדפדפן

הדפדפן מריץ את הפרויקט כמעט לגמרי לוקאלית. מצב האפליקציה מנוהל ב-`webapp/assets/app.js` דרך אובייקט `state` יחיד שמכיל את הסבשן הפעיל, מכונת המצבים, אלמנטי DOM והמשתמש המחובר.

### נקודת הכניסה (index.html)

הקובץ [webapp/index.html](../webapp/index.html) מגדיר שלושה מצבי תצוגה על ה-body דרך `data-view`:

- `landing` - הדף הראשי עם hero + רשימת תרגילים
- `live` - מסך המצלמה עם השלד + HUD + מד עומק + פס Coach
- `summary` - מסך סיכום בסוף הסבשן

במעלה הראש נטענים fonts, favicon, apple-touch-icon, manifest.webmanifest, ותגיות `apple-mobile-web-app-*` שגורמות ל-iOS להתייחס להוספה למסך הבית כאפליקציה עצמאית.

```html
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="apple-touch-icon" href="apple-touch-icon.svg">
<link rel="manifest" href="manifest.webmanifest">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="PhysioLive">
```

### ניהול המצב הגלובלי (app.js)

בתחילת `app.js` מוגדר אובייקט `state` יחיד שמאגד את כל מה שהאפליקציה זוכרת בזמן ריצה:

```js
const state = {
  exerciseId: "squat",
  view: "landing",
  running: false,
  video: null,
  canvas: null,
  ctx: null,
  stream: null,
  loopHandle: null,
  repCounter: null,
  sessionId: null,
  reps: [],
  stats: { good: 0, warn: 0, bad: 0 },
  startedAt: 0,
  timerHandle: null,
  lastCoachTs: 0,
  cameras: [],
  activeCameraId: null,
  activeFacing: "user",
  framingMissingFrames: 0,
  framingHintActive: false,
  camReadyEventFired: false,
  posesSeen: 0,
  handsSeen: 0,
  cameraOpenedAt: 0,
  debugAutoShown: false,
};
```

כל השדות הללו מתעדכנים על ידי לולאת ה-frame הראשית, אירועי DOM, ותשובות רשת. אין state מפוזר במודולים אחרים.

### זיהוי פוזה (pose.js)

הקובץ [webapp/assets/pose.js](../webapp/assets/pose.js) עוטף שני מודלים של MediaPipe Tasks Vision:

- `PoseLandmarker` עם `pose_landmarker_full.task` (~7 MB) שמחזיר 33 נקודות ציון של הגוף.
- `HandLandmarker` עם `hand_landmarker.task` (~5 MB) שמחזיר עד 21 נקודות לכל יד, עד 2 ידיים.

הפונקציה `inferPose` מריצה את שני המודלים במקביל וממזגת את התוצאה לאובייקט אחד:

```js
export async function inferPose(video, ts) {
  const pose = await ensurePose();
  if (video.readyState < 2) return null;
  const poseResult = pose.detectForVideo(video, ts);
  const body = (poseResult && poseResult.landmarks
                && poseResult.landmarks[0]) || null;
  let hands = null, handedness = null;
  if (_hand && !_handInitFailed) {
    try {
      const hr = _hand.detectForVideo(video, ts);
      if (hr && hr.landmarks && hr.landmarks.length) {
        hands = hr.landmarks;
        handedness = (hr.handedness || []).map(h => h && h[0]
          ? { label: h[0].categoryName, score: h[0].score }
          : null);
      }
    } catch (e) {
      console.warn("hand inference error", e);
    }
  }
  if (!body && !hands) return null;
  return { pose: body, hands, handedness };
}
```

הציור על ה-canvas מבוצע על ידי `drawSkeleton` שמצייר קודם את שלד הגוף בקבוצות צבע, ואז שני שלדי ידיים בצבע ציאן (יד ימין) וורוד (יד שמאל).

### חישוב זוויות (angles.js)

הקובץ [webapp/assets/angles.js](../webapp/assets/angles.js) הוא מירר של `src/app/angles.py`. כל פונקציה מחזירה `null` אם visibility של אחת מנקודות הציון נופלת מתחת ל-0.4:

```js
export function kneeAngle(lm, side) {
  const [hip, knee, ankle] = side === "left"
    ? [MP.L_HIP, MP.L_KNEE, MP.L_ANKLE]
    : [MP.R_HIP, MP.R_KNEE, MP.R_ANKLE];
  const a = pt(lm, hip), b = pt(lm, knee), c = pt(lm, ankle);
  if (!a || !b || !c) return null;
  return angle3(a, b, c);
}
```

הפונקציה המרכזית `allAngles` מפעילה את כל החישובים ומחזירה dict אחד עם כל הזוויות ומדדי העזר (`torso_vertical`, `knee_over_toe_left`, וכו').

### ספירת חזרות (rep_counter.js)

הקובץ [webapp/assets/rep_counter.js](../webapp/assets/rep_counter.js) מיישם מכונת מצבים דטרמיניסטית עם שני מצבים ראשיים: `STANDING` ו-`BOTTOM`. הוא נועד להיות עמיד לרעש בקלט:

- **סובלנות לרעש**: אם `primaryAngle` חוזר `null` עד 5 frames רצופים, המצב לא מתאפס. זה מונע איפוס בזמן דרופ קצר של visibility.
- **shallowDeg**: אם המשתמש הגיע לסף רדוד יותר מ-bottomDeg אבל לא ליעד המלא, החזרה עדיין נספרת אבל מסומנת `shallow: true` וה-rule engine יפיק verdict "Rep counted, but shallow".
- **בילטראלי**: תרגילים כמו סקוואט וגלוט-ברידג' מסומנים `bilateral: true` בקונפיג. פונקציית `pickPrimary` ב-`app.js` מחזירה `null` אם רק צד אחד גלוי, מה שמונע ספירה של הרמת רגל אחת כחזרת סקוואט.

ה-getter שמחזיר את השלב לתצוגה:

```js
get displayPhase() {
  if (this.state === "STANDING" && this._downHits > 0) return "DESCENDING";
  if (this.state === "BOTTOM"  && this._upHits > 0)  return "RISING";
  return this.state;
}
```

ה-HUD מציג את זה במקום רק `STANDING/BOTTOM`, כדי שהמשתמש יראה תגובה מיידית בזמן ירידה או עלייה.

### חוקי פורם (rules.js)

הקובץ [webapp/assets/rules.js](../webapp/assets/rules.js) הוא evaluator דטרמיניסטי לפי סוגי תנאים. הקונפיג של כל תרגיל מגדיר את החוקים ב-`exercises.js`:

```js
squat: {
  id: "squat",
  name: "Squat",
  repGoal: 12,
  repDef: {
    primary: "knee",
    standingDeg: 170,
    bottomDeg: 100,
    shallowDeg: 130,
    hysteresisDeg: 8,
    confirmFrames: 2,
    bilateral: true,
  },
  rules: [
    { id: "shallow_depth", level: "warn",
      message: "Shallow rep. Try to go deeper within your range.",
      condition: { kind: "rom_below", targetMaxDeg: 115 } },
    { id: "knee_over_toe", level: "warn",
      message: "Knee is past the toe. Keep the knee over the ankle.",
      condition: { kind: "knee_over_toe_side", thresholdNorm: 0.35 } },
    { id: "torso_lean", level: "warn",
      message: "Torso leaning too far forward. Engage the core...",
      condition: { kind: "torso_vertical_gt", thresholdDeg: 45 } },
  ],
},
```

הפונקציה `evaluate(sample, rules)` עוברת על כל החוקים, אוספת את ההפרות, ובוחרת את ההפרה עם החומרה הגבוהה ביותר לתצוגה.

### תזמון פתיחת המצלמה (openCameraStream)

iOS Safari דורש טיפול מיוחד. הקוד ב-`app.js` פותח סולם fallback:

```js
async function openCameraStream(preferredDeviceId) {
  if (state.stream) {
    state.stream.getTracks().forEach(t => t.stop());
    state.stream = null;
  }
  const attempts = [];
  if (preferredDeviceId) {
    attempts.push({ video: { deviceId: { exact: preferredDeviceId },
                             width: { ideal: 1280 },
                             height: { ideal: 720 } },
                    audio: false });
  }
  attempts.push({ video: { facingMode: { ideal: "user" },
                           width: { ideal: 1280 },
                           height: { ideal: 720 } },
                  audio: false });
  attempts.push({ video: { facingMode: { ideal: "environment" },
                           width: { ideal: 1280 },
                           height: { ideal: 720 } },
                  audio: false });
  attempts.push({ video: true, audio: false });

  let stream = null, lastError = null;
  for (const constraints of attempts) {
    try {
      stream = await navigator.mediaDevices.getUserMedia(constraints);
      if (stream && stream.getVideoTracks().length) break;
    } catch (e) { lastError = e; }
  }
  if (!stream) throw lastError || new Error("Could not open any camera");
  ...
}
```

עוד עידונים ל-iOS: הקוד לא מאפס `srcObject` ל-null בין stream ל-stream (טריגר מוכר של black-video). הוא מוודא ש-`playsinline` ו-`muted` נקבעים לפני srcObject, ומטפל ב-play() rejection על ידי המתנה ל-`loadedmetadata` ולאחריה `load()` fallback.

### חיווי חי (updateDepthIndicator, updateFormFlash)

תוך כדי הרפ עצמו, לא רק בסופו, ה-HUD מציג:

- **מד עומק אחוזי** בין 0% (עומד) ל-100%+ (הגיע ליעד bottom). מוצג כפס אופקי מתחת ל-HUD, נצבע צהוב מ-60% וירוק ב-100%.

```js
function updateDepthIndicator(primary, ex) {
  const bar = document.getElementById("depth-fill");
  const pctEl = document.getElementById("depth-pct");
  if (!bar || !pctEl) return;
  const { standingDeg, bottomDeg } = ex.repDef;
  const range = standingDeg - bottomDeg;
  let pct = 0;
  if (primary != null && range !== 0) {
    pct = ((standingDeg - primary) / range) * 100;
  }
  pct = Math.max(0, Math.min(120, pct));
  bar.style.width = `${Math.min(100, pct)}%`;
  bar.dataset.state = pct >= 100 ? "hit" : (pct >= 60 ? "close" : "");
  pctEl.textContent = `${Math.round(pct)}%`;
}
```

- **הבזק אדום על טבעת ה-HUD** ברגע ש-knee-over-toe או torso-lean חוצים סף באמצע החזרה. הוא לא ממתין לסגירת החזרה.

### אותנטיקציה (auth.js)

אין מצב אורח. כדי להיכנס למצלמה חייבים להיות מחוברים. שני נתיבים:

- **Google Sign-In**: מרנדר את הכפתור של Google Identity Services, מקבל ID token, שולח ל-`/auth/google` שבודק אותו מול Google + email whitelist ומחזיר JWT.
- **Passphrase**: המשתמש מקליד סיסמה משותפת, נשלחת ל-`/auth/login`, ה-VM משווה מול `PHYSIOLIVE_PASSPHRASE_HASH` (bcrypt) או `PHYSIOLIVE_PASSPHRASE` (plain, ל-first-boot smoke test) ומחזיר JWT.

ה-JWT נשמר ב-localStorage ומוצמד ל-`Authorization: Bearer <jwt>` בכל בקשה יוצאת:

```js
export function authHeader() {
  const jwt = getStoredJwt();
  return jwt ? { Authorization: `Bearer ${jwt}` } : {};
}
```

בהתנתקות ה-JWT נמחק וגם ה-profile ב-localStorage. הכפתור למעלה מימין מציג popover קטן (`Signed in as X` + Sign out) במקום להתנתק מיידית.

### לקוח Coach (coach_client.js)

הקובץ [webapp/assets/coach_client.js](../webapp/assets/coach_client.js) שולח את תוצאת הרפ ל-VM. הוא:

- מציב `MIN_GAP_MS = 2500` כדי לא לדגם את השרת ברצף מהיר.
- מציב timeout של 18 שניות כי `openai/gpt-oss-120b` מגיב תוך 6-12 שניות.
- מזהה תשובות 401/403 (JWT פג תוקף) ו-429 (rate limit) ומחזיר קודי שגיאה ברורים ל-`app.js`.

```js
const res = await fetch(`${origin}/coach/feedback`, {
  method: "POST",
  headers,
  body: JSON.stringify({
    exercise, verdict_level: verdictLevel,
    verdict_text: verdictText, metrics,
  }),
  signal: controller.signal,
});
```

### לקוח דוח יומי (report_client.js)

הקובץ [webapp/assets/report_client.js](../webapp/assets/report_client.js) מוודא שמשלוח הדוח מאגרג רק את הסבשנים שהתחילו היום, ומטפל בכל השגיאות המצופות:

```js
function _todaysSessions(sessions) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const cutoff = today.getTime();
  return (sessions || []).filter(s => s.startedAt && s.startedAt >= cutoff);
}
```

הוא נקרא אוטומטית ב-endSession (silent), וגם דרך כפתור "Email today's summary" במסך הסיכום עם משוב טוסט למשתמש.

---

## VM Backend - שרת FastAPI

הכל בפולדר `src/vm/`. השירות רץ תחת systemd כמשתמש `physiolive`, קורא env מ-`/etc/physiolive/env`, ומוגבל ל-700 MB RAM כדי לא להפיל את ה-e2-micro.

### api.py - endpoints

הקובץ [src/vm/api.py](../src/vm/api.py) מרכיב את כל ה-endpoints:

| Endpoint | Auth | תיאור |
|---|---|---|
| `GET  /health` | Public | סטטוס + גרסה + `chunks_count` |
| `POST /auth/login` | Public | passphrase -> JWT |
| `POST /auth/google` | Public | Google id_token -> JWT |
| `POST /rag/query` | JWT | חיפוש vector-store, מחזיר top-k chunks |
| `POST /coach/feedback` | JWT | retrieval + LLM composition |
| `POST /report/daily/send` | JWT | דוח יומי במייל |

הכל עטוף ב-`@limiter.limit(...)` מ-slowapi עם מפתח שמעדיף JWT sub על IP, כדי שמשתמש שעובר בין רשתות לא ימצה בטעות את המכסה של רשת אחת.

CORS פתוח לכל ה-origins כי הדפדפן על GitHub Pages הוא cross-origin לעומת ה-tunnel, אבל ה-JWT הוא השער האמיתי:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-Id"],
    max_age=86400,
)
```

### auth.py - JWT + Google + Passphrase

הקובץ [src/vm/auth.py](../src/vm/auth.py) מטפל בכל תהליך ההזדהות:

- `issue_passphrase_token()` משווה את הסיסמה שנשלחה מול bcrypt hash או plain form, ומחזיר `{jwt, exp, profile}`.
- `issue_google_token()` פונה ל-`oauth2.googleapis.com/tokeninfo`, מוודא את audience, verified email, ובודק אותו מול `PHYSIOLIVE_ALLOWED_EMAILS`.
- `require_auth()` היא dependency של FastAPI שמפענחת Bearer JWT ומחזירה את ה-claims ל-route handlers.
- `_get_or_create_secret()` דואג למפתח חתימת JWT: קודם קורא מ-env, אחר כך מ-`/var/lib/physiolive/jwt.secret`, אחר כך מייצר באמצעות `secrets.token_bytes(64)` ושומר עם הרשאות 600.

מזהה המשתמש (`sub`) מיוצר על ידי hash של email + source + secret, כך שהמייל הפרטי לא זולג לאף log:

```python
def _stable_sub(email: str, source: str) -> str:
    h = hashlib.sha256()
    h.update(_get_or_create_secret())
    h.update(b"|")
    h.update(source.encode())
    h.update(b"|")
    h.update(email.lower().encode())
    return "u_" + h.hexdigest()[:24]
```

### coach_llm.py - Groq client + Llama fallback לוקאלי

הקובץ [src/vm/coach_llm.py](../src/vm/coach_llm.py) מבצע את קריאת ה-LLM. הוא תומך בשלושה ספקים דרך `COACH_PROVIDER`:

- **groq** (ברירת מחדל) - `openai/gpt-oss-120b` ב-Groq free tier.
- **anthropic** - קריאה ל-Anthropic Messages API (דורש `ANTHROPIC_API_KEY` ו-`ANTHROPIC_MODEL`).
- **local** - הרצת inference ישירות על ה-VM עם Llama 3.2 1B Instruct דרך `llama-cpp-python`.

**Fallback אוטומטי**: כאשר `COACH_PROVIDER=groq` וקריאת Groq נכשלת (rate limit, network, 5xx, timeout), הקוד נופל אוטומטית ל-Llama לוקאלי. כך גם השבתה של Groq לא משתיקה את ה-Coach. הקוד מתעד את המעבר ב-log:

```
coach: Groq failed (HTTPStatusError: 429 Too Many Requests), falling through to local Llama fallback
```

הקריאה ל-Groq משתמשת ב-`openai/gpt-oss-20b` כברירת מחדל של הקוד, אך ה-env של הפריסה מגדיר `GROQ_MODEL=openai/gpt-oss-120b` כדי לקבל איכות טובה יותר. הפרמטרים העיקריים: `reasoning_effort=low` ו-`max_tokens=800`:

```python
payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ],
    "max_tokens": 800,
    "temperature": 0.6,
}
if model.startswith("openai/gpt-oss"):
    payload["reasoning_effort"] = "low"
```

ה-SYSTEM_PROMPT מכריח את המודל להרכיב משפט חדש במקום להעתיק את פסיקת החוקים, ולצטט לכל היותר chunk אחד מהעדות שהועברה אליו.

fallback חכם ל-gpt-oss: אם השדה `content` מגיע ריק, הקוד מנסה לקרוא את `reasoning` ומחלץ את המשפט האחרון בעל אורך משמעותי כתחליף. זה פותר את הבאג ש-max_tokens קטן מדי גורם למודל לצרוך את כל התקציב על chain-of-thought בלי להשאיר מקום ל-content.

ה-Llama הלוקאלי טוען lazy - רק כשמפעילים אותו בפעם הראשונה (בזמן Groq failure או כשהוא ה-primary provider). המודל נשאר בזיכרון בין קריאות כך שקריאות עוקבות משלמות רק את זמן ה-inference (~8-15 שנ' על 2 vCPU). ה-config שלו: `PHYSIOLIVE_LOCAL_LLM_MODEL`, `PHYSIOLIVE_LOCAL_LLM_CTX` (default 1024), `PHYSIOLIVE_LOCAL_LLM_THREADS` (default 2), ו-`PHYSIOLIVE_LOCAL_LLM_MAX_TOKENS` (default 140). מדריך התקנה מלא ב-[src/vm/deploy/local-llm.md](../src/vm/deploy/local-llm.md).

### email_report.py - דוח מייל

הקובץ [src/vm/email_report.py](../src/vm/email_report.py) מבצע שלושה שלבים:

1. **Aggregate**: הופך את רשימת הסבשנים למבנה מסודר עם מספרי sums, אחוזי טופס טוב, ממוצע זווית מינ' פר תרגיל, וטופ 5 cues שחזרו.

2. **Clinical opinion (LLM)**: מזמין את `openai/gpt-oss-120b` לכתוב דעה קלינית של 4-6 משפטים ישירות למטופל, עם הוראות ברורות שלא להמציא מספרים.

3. **SMTP send**: מכין `EmailMessage` עם גרסת plain + HTML, ושולח דרך `smtplib.SMTP(smtp_host, smtp_port).starttls().login().send_message()`.

ה-ledger `sent_reports.db` מונע שליחה כפולה באותו יום:

```python
def already_sent_today(user_sub: str, today_ymd: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM sent_reports WHERE user_sub=? AND ymd=?",
            (user_sub, today_ymd),
        ).fetchone()
    return row is not None
```

### RAG (embedder + store + query)

השכבה החכמה הזאת חיה בפולדר `src/app/rag/`:

- `embedder.py` עוטף את ONNX all-MiniLM-L6-v2 שמגיע מובנה עם ChromaDB. אין צורך ב-sentence-transformers/PyTorch/CUDA - טעינת המודל תופסת ~90 MB RAM.
- `store.py` מנהל את ה-persistent ChromaDB תחת `data/chroma/`. מספק `add_evidence`, `search`, `count_evidence`.
- `corpus.py` מכיל את `SeedCorpus` שמאתחל את ה-store מ-`corpus/**/chunks.json` ו-`data/corpus_seed/*.json` (dedup by id), ואת `PubMedFetcher` שקורא ל-NCBI E-utilities.
- `query.py` בונה את שאילתת ה-retrieval מתוך פסיקת החוקים והמדדים, וממטב את ה-tags כדי להחזיר עדות רלוונטית.
- `pubmed_queries.py` היא רשימת 24 שאילתות ברירת המחדל של הפקודה `--pubmed 25`, שמגדילה את הקורפוס ל-500-700 chunks.

---

## הקורפוס המדעי

### שכבת ה-seed

ב-`corpus/` שוכנים 15 chunks שנכתבו ידנית, עם schema קבוע:

```json
{
  "id": "squat-depth-01",
  "title": "Squat depth and knee flexion",
  "section": "squat technique",
  "text": "During a rehabilitation squat, knee flexion is typically progressed within a pain-free range. A commonly cited target for functional strength is a knee angle of about 90 degrees ...",
  "source_url": "https://www.apta.org/",
  "license": "Reference only - see APTA general guidance",
  "evidence_level": "guideline",
  "tags": ["squat", "knee", "ROM", "rehabilitation"],
  "body_part": "knee"
}
```

הם מכסים את הנושאים שנדרשים לחוקים הדטרמיניסטיים: עומק סקוואט, יישור ברך מעל הקרסול, שיפוע גו, dynamic valgus, glute medius, ROM utilisation, סימטריה בין גפיים, אזהרות כאב, warm-up.

### שכבת PubMed

הפקודה `python -m app.tools.build_index --pubmed 25` מריצה את כל 24 השאילתות ב-`pubmed_queries.py` מול NCBI E-utilities. כל שאילתה שולפת 25 abstracts, כל abstract מתחלק ל-chunks של ~512 מילים, וכל chunk מוטבע ומועבר ל-ChromaDB. התוצאה: 500-700 chunks אמיתיים עם source URLs של `pubmed.ncbi.nlm.nih.gov/<pmid>/`.

השאילתות בפועל מכסות סקוואט, פסיעה קדימה (lunge), ברך, ACL, dynamic valgus, גרסאות של glute, straight leg raise, post-op, meniscus, כתף, rotator cuff, low back, ROM, eccentric loading, proprioception, warm-up, adherence.

בדיקת מספר chunks:

```bash
python -c "from app.rag.store import Store; print(Store().count_evidence())"
```

או דרך ה-endpoint:

```bash
curl -s https://<tunnel>.trycloudflare.com/health | jq .chunks_count
```

---

## פריסה מלאה

### GitHub Pages (workflow)

הקובץ [.github/workflows/pages.yml](../.github/workflows/pages.yml) פורס את `webapp/` על כל push ל-main שנוגע בקבצי ה-webapp. השירות מגיע ל-URL:

```
https://orarr2.github.io/PhysioLive_Product/
```

הפעלה חד-פעמית בהגדרות: Repo Settings > Pages > Source = GitHub Actions.

### VM setup (setup.sh)

הריצה של [src/vm/deploy/setup.sh](../src/vm/deploy/setup.sh) על Debian 12 e2-micro מבצעת:

1. `apt install` של python3-full, sqlite3, git, curl, ufw.
2. יצירת המשתמש `physiolive` ותיקיות הריצה.
3. `git clone` של הריפו ל-`/opt/physiolive/repo`.
4. הקמת venv ב-`/opt/physiolive/venv` והתקנת `src/vm/requirements.txt`.
5. אתחול `/etc/physiolive/env` עם placeholders ל-Groq, passphrase, JWT secret, allowed emails, ו-Gmail SMTP.
6. בנייה ראשונית של ChromaDB מ-`corpus/`.
7. התקנת ה-systemd unit ו-`systemctl enable physiolive`.
8. הגדרת `ufw` שחוסמת inbound חוץ מ-SSH.

הפקודה בפועל שרצה על VM חדש:

```bash
curl -L https://raw.githubusercontent.com/orarr2/PhysioLive_Product/main/src/vm/deploy/setup.sh -o setup.sh
sudo bash setup.sh
sudo nano /etc/physiolive/env      # ערוך את GROQ_API_KEY, PHYSIOLIVE_PASSPHRASE
sudo systemctl start physiolive
curl http://127.0.0.1:8000/health
```

### Cloudflare Tunnel

`cloudflared` מריץ tunnel יוצא (outbound-only) שחושף את `127.0.0.1:8000` ל-URL של `<random>.trycloudflare.com` בלי לפתוח פורטים ב-firewall. הפקודה שמפעילה אותו ב-VM:

```bash
sudo cloudflared tunnel --url http://127.0.0.1:8000 --no-autoupdate
```

ה-URL של TryCloudflare מתחלף בכל restart של cloudflared. לכן יש publisher.

### Tunnel URL auto-publisher

הזוג `publish-tunnel-url.path` + `publish-tunnel-url.service` תחת [src/vm/deploy/](../src/vm/deploy/) עוקבים אחרי `/var/log/cloudflared-url.txt`. בכל שינוי הם קוראים את ה-URL העדכני ומריצים את הסקריפט [src/vm/deploy/publish-tunnel-url.sh](../src/vm/deploy/publish-tunnel-url.sh) שדוחף אותו ל-`webapp/tunnel-url.json` בענף `main` דרך GitHub Contents API.

Config של הפרסום נמצא ב-`/etc/physiolive/tunnel-publisher.env`:

```
GITHUB_TOKEN=github_pat_XXXXXXXXXXXXXXXXXXXX
GITHUB_REPO=orarr2/PhysioLive_Product
GITHUB_BRANCH=main
```

התוצאה: אחרי כל reboot של cloudflared, בתוך 60-90 שניות GitHub Pages פורס גרסה עדכנית ו-`webapp/assets/config.js` דרך `resolveVmOrigin()` קורא את ה-URL החדש.

---

## אבטחה, JWT ו-Rate Limits

### שכבות ה-rate-limit

`docs/rate-limits.md` מפרט כל שכבה. תמצית:

- **דפדפן**: `MIN_GAP_MS = 2500` בין קריאות coach.
- **VM per-key** (JWT sub או IP): 30/min + 500/day על כל הroutes.
- **VM per-user** (JWT sub): 20/min על `/rag/query` ו-`/coach/feedback`.
- **Groq free tier**: 30/min ו-1000/day למודל `openai/gpt-oss-120b`.

כל ה-limits ניתנים להתאמה דרך env vars:

```
PHYSIOLIVE_LIMIT_PER_MIN=30/minute
PHYSIOLIVE_LIMIT_PER_DAY=500/day
PHYSIOLIVE_USER_LIMIT=20/minute
```

### JWT

מפתח חתימה HS256 נשמר ב-`/var/lib/physiolive/jwt.secret` (chmod 600). TTL של הטוקן הוא 7 ימים לפי `PHYSIOLIVE_JWT_TTL=604800`. סיבוב המפתח פוסל את כל הטוקנים הקיימים.

### CORS

פתוח לכל origin, אבל `allow_credentials=False` ו-`allow_headers=[...]` מוגבלים.

---

## דוח מייל יומי

### תהליך end-to-end

1. בסוף כל סבשן, `endSession()` ב-`app.js` קורא ל-`triggerDailyReport(uid, {silent: true})`.
2. `sendDailyReport(uid, sessions)` ב-`report_client.js` מסנן את הסבשנים של היום ושולח POST ל-`/report/daily/send`.
3. ה-VM ב-`api.py::report_daily_send` מחליט אם צריך לשלוח (חד-פעמי ליום פר משתמש), פונה ל-`send_daily_report()` ב-`email_report.py`.
4. `email_report._aggregate()` מכין מבנה מסודר של סיכומים.
5. `email_report._clinical_opinion()` פונה ל-Groq עם ה-summary ומקבל 4-6 משפטים של דעה קלינית.
6. `email_report.send_daily_report()` בונה HTML + plain, ומעביר ב-Gmail SMTP.
7. ה-ledger `sent_reports.db` מסמן שהמשתמש קיבל דוח היום.

### מבנה המייל

Subject: `PhysioLive daily summary (2026-09-21) - 12 reps`

תוכן HTML:

- ראש עם שם המשתמש, תאריך, סך סבשנים וסך חזרות.
- טבלה: תרגיל, מספר חזרות, אחוז טופס טוב, ממוצע זווית מינ', טופ cues.
- Clinical opinion של Llama במסגרת נפרדת.
- Footer עם timestamp.

### כפתור ידני

מסך הסיכום מציג כפתור "Email today's summary". קליק מפעיל את אותו נתיב עם `silent: false` שמציג toasts של הצלחה או שגיאה.

---

## פיתוח מקומי + מחברת ה-Python

### הרצה מקומית של ה-webapp

```bash
python -m http.server 8080 --directory webapp
```

פתח `http://localhost:8080` בכרום או ספארי. המצלמה דורשת secure origin, אז localhost מותר אבל LAN דורש mkcert או self-signed HTTPS.

### מחברת שולחן העבודה

הקובץ `physio_live.ipynb` מריץ את הפייפליין המלא על CPU של לפטופ עם webcam או stream של טלפון. Run All יפתח דשבורד ב-`http://localhost:8000` עם השלד החי, ספירת חזרות, ו-verdicts. שימושי לניתוח אחורי של הסבשן, וגם כשה-VM לא זמין.

### שרת FastAPI לוקאלית

לפיתוח ב-VM אפשר להריץ ידנית:

```bash
cd src
PYTHONPATH=src PHYSIOLIVE_AUTH_DISABLED=1 \
uvicorn vm.api:app --host 127.0.0.1 --port 8000 --reload
```

`PHYSIOLIVE_AUTH_DISABLED=1` מדלג על JWT בפיתוח בלבד.

---

## מסלול הפיתוח

הגרסה הנוכחית של ה-VM: `1.2.0`.

Milestones עיקריים שהושלמו:

- הקמת הריפו על `main` ב-`github.com/orarr2/PhysioLive_Product`.
- Skeleton חי (MediaPipe Holistic) על מחברת שולחן עבודה.
- MVP סקוואט: מכונת מצבים + חוקי פורם + verdicts.
- שדרוג ל-33 body + 21x2 hand landmarks.
- RAG מקומי: ChromaDB + ONNX all-MiniLM-L6-v2.
- Coach agent מקומי ו-remote (Groq/Anthropic).
- 5 תרגילים + rules לכל אחד.
- Session persistence ב-SQLite.
- Signatures מ-7 סרטוני סקוואט.
- Curator ל-YouTube ו-PubMed.
- Personalization / calibration wizard.
- Web App מלאה: MediaPipe Tasks Vision, iOS Safari fixes, sign-in modal.
- Auth v2: JWT + Google + passphrase.
- Rate limits per-IP + per-user.
- Tunnel URL auto-publisher.
- Corpus restructure ArchiveX-style + 24 PubMed queries.
- דוח מייל יומי + חיווי חי במהלך רפ + bilateral gate + shallow verdict.

מה שנמצא בתור פתוח (task 16):

- אימון LightGBM classifier על UI-PRMD כדי להוסיף verdict נוסף מעבר לחוקים.

עוד רעיונות שלא הוחלט עליהם:

- Local LLM על ה-VM (Llama 3.2 1B q4 כ-fallback ל-Groq).
- SQLite cache לתשובות coach על verdicts דומים.
- Sync היסטוריית סבשן לענן (currently localStorage בלבד).

---

## מקורות נוספים

- [README.md](../README.md) - סקירה תמציתית באנגלית.
- [webapp/README.md](../webapp/README.md) - מבנה מודולי ה-webapp.
- [src/vm/deploy/README.md](../src/vm/deploy/README.md) - env vars מלאים ל-VM.
- [src/vm/deploy/cloudflared.md](../src/vm/deploy/cloudflared.md) - הקמת tunnel.
- [src/vm/deploy/tunnel-publisher.md](../src/vm/deploy/tunnel-publisher.md) - הקמת publisher.
- [docs/rate-limits.md](rate-limits.md) - כל תקרות ה-throughput.
- [docs/deployment.md](deployment.md) - מדריך פריסה end-to-end.
- [corpus/README.md](../corpus/README.md) - שכבות הקורפוס והשאילתות.
- [corpus/CONTRIBUTING.md](../corpus/CONTRIBUTING.md) - איך מוסיפים chunk.

</div>
