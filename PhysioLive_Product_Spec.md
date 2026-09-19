# PhysioLive — מסמך אפיון מוצר, ידע וארכיטקטורה

**גרסה:** 1.0 · **סטטוס:** אפיון מקדים לאישור לפני מימוש · **מסמך:** Product & Engineering Spec

---

## 0. תקציר מנהלים

**PhysioLive** הוא מאמן שיקום פיזיותרפי חי, מבוסס ראיית מחשב, שרץ ממחברת פייתון אחת על הלפטופ של המשתמש. המצלמה המובנית (או מצלמת סמארטפון בזרימת רשת) קולטת את התרגיל, שלד 17-נקודות מזוהה בזמן אמת, זוויות מפרקים מחושבות פר-פריים, וכל חזרה מקבלת ציון תקינות אל-מול בסיס ידע (**RAG**) שנבנה מקורפוס מדעי של פיזיותרפיה ומדגם וידאו מקצועי מתויג. משוב חזותי מצויר על הפריים, משוב קולי מוזרם ב-TTS, ומחקר ה-RAG מחזיר למשתמש הסבר קצר מבוסס-מקורות. מסד הידע והאינדקסים חיים על **מכונה וירטואלית קטנה (e2-micro, 1 GB) ב-Google Cloud** שרצה 24/7 בשכבה החינמית, ומחזירה תשובות ל-clients מקומיים דרך API. שילוב **סוכני AI** (Coach, Analyzer, Curator, Progress) מנהל את הזרימה - כל סוכן עם אחריות אחת ותפקיד ברור.

**סלוגן פנימי:** *מחברת אחת. מצלמה אחת. פיזיותרפיסט בכיס.*

---

## 1. בעיית מוצר

### 1.1 מטופלים
- מבצעים תרגילים בבית לא נכון, מחריפים פציעות, מפסיקים באמצע פרוטוקול.
- לא יודעים לזהות בעצמם מתי הטכניקה סטתה - הפיזיותרפיסט זמין רק פעם בשבוע.
- אין ספירת חזרות אמינה, אין מדידת טווח (ROM) אובייקטיבית, אין תיעוד של סשן.

### 1.2 פיזיותרפיסטים
- לא רואים מה קרה בין הפגישות.
- מסתמכים על דיווח מילולי של המטופל ("עשיתי 3×10").
- אין ראיות אובייקטיביות לשיפור או להידרדרות.

### 1.3 פתרונות קיימים (הרפרנס PhysioVision, אפליקציות פופולריות)
- דורשים 3+ שירותים (Frontend/Backend/Vision), MERN, GPU, ענן.
- ידע מובנה קטן, ללא ציטוט מקורות - קשה לסמוך.
- לא רצים אצל המטופל הביתי הממוצע שאין לו GPU.

**PhysioLive** מטפל בכל אחת מהחוליות הללו בפתרון מינימלי: מחברת + VM חינמית + RAG על קורפוס מדעי אמיתי.

---

## 2. הטמעה של הידע והתשתית מהריפו הקיים (YOLO26)

הריפו הנוכחי כבר הוכיח:

| רכיב קיים | שימוש חוזר ב-PhysioLive |
|---|---|
| `pose.py` — COCO-17, הפרדת ימין/שמאל, gate של `KP_MIN_CONF=0.30` | ליבת השלד — מועבר כמעט 1:1 |
| ריצת YOLO ב-OpenVINO CPU | אותה תשתית inference; מודל pose במקום detection |
| Two-tick confirmation (fire, LPR) | חזרה נספרת רק אחרי 2 פריימים רצופים בטווח |
| Debounce להתראות | הודעת קול נשלחת פעם אחת לחזרה |
| Dashboard 3-טאבים (Analysis / Investigation / Model info) | Live / Session / Progress |
| שרת `serve.py` על localhost | זהה, פתיחת דשבורד בדפדפן |
| שמירת snapshot לאירוע | כל חזרה שומרת פריים-שיא |
| מודל `behavior.py` (חשד לנפילה) | חשד לאיבוד שיווי משקל בתרגילי עמידה |
| מבנה `notebook + src/ + web/ + media/` + `Run All` | תבנית ישירה |
| מדיניות "לא ממציאים אם לא רואים" | לא מזעיקים על צורה שגויה אם המפרק לא נראה |

**מה נזרק:** LPR, פנים, שריפה, חניות, קווי חצייה, heatmap, `yt-dlp`, `screen_capture`, `reid` — לא רלוונטיים לפרויקט אדם-אחד ובית.

---

## 3. בסיס הידע (RAG) — הלב האינטלקטואלי של המוצר

זו הבעיה הכי גדולה שהמוצר פותר וה"מה שחסר" שהצבעת עליו. הפירוט הבא הוא לב המסמך.

### 3.1 שלוש רגליים של בסיס הידע

```
┌──────────────────────────────────────────────────────────────┐
│                    Knowledge Base (RAG)                      │
├────────────────┬──────────────────────┬──────────────────────┤
│ 1. קורפוס מדעי │ 2. וידאו מקצועי      │ 3. וידאו קהילתי       │
│    טקסטואלי    │    מתויג             │    (YouTube/Reels)    │
│                │                       │                      │
│  → הסברים,     │  → "אמת קרקע"        │  → הרחבת דאטה         │
│    הצדקות      │    לגזירת            │    לאימון             │
│    רפואיות     │    זוויות/טווח       │    ולסינון           │
└────────────────┴──────────────────────┴──────────────────────┘
```

### 3.2 רגל 1 — קורפוס מדעי טקסטואלי

**מקורות (הכל פתוח או במסלול חוקי):**

| מקור | תוכן | היקף ראשוני |
|---|---|---|
| PubMed / PMC (Open Access) | מאמרים על שיקום ברך, כתף, גב תחתון, שריר-שלד | ~2,000 abstracts + 500 full-text OA |
| Cochrane Reviews (תקצירים פתוחים) | סקירות שיטתיות של יעילות פרוטוקולי שיקום | ~150 |
| PEDro (Physiotherapy Evidence Database) | ציוני איכות מחקרית לפרוטוקולים | מטא-דאטה בלבד |
| NIH / CDC / WHO guidelines | הנחיות רשמיות לתרגילי טיפול | ~50 מסמכים |
| ספרי לימוד בקוד פתוח (OpenStax Anatomy, WikiEM) | אנטומיה שלד-שריר, ביומכניקה | ~10 ספרים |
| APTA / Physiopedia (creative commons מסוימים) | טכניקות והוראה קלינית | ~800 ערכים |
| כתבי-עת עם רישיון פתוח (JOSPT open articles, BMJ Open) | מקרים ופרוטוקולים ספציפיים | ~300 |

**עקרונות איסוף:**
- **רישוי:** רק Open Access, Creative Commons, או Fair Use מוגבל. כל פריט נשמר עם `license` ו-`source_url`.
- **תיוג כפול:** כל chunk מקבל תגיות: `body_part` (ברך/כתף/גב), `condition` (ACL/CTS/סקוליוזיס), `intervention` (סקוואט/מתיחה), `evidence_level` (RCT/סקירה/דעה).
- **ניקוי:** הסרת כותרות תחתונות, מספרי עמוד, ביבליוגרפיה, טבלאות שאינן NL.

### 3.3 רגל 2 — וידאו מקצועי מתויג (Ground-truth)

**מטרה:** לכל תרגיל, סרטון "אמת" של פיזיותרפיסט מוסמך המבצע את התרגיל נכון, שמפיק **חתימות זוויות ידועות** (angle signatures) שהמוצר משווה אליהן.

**מקורות:**
- הקלטות שהמפתח מפיק בעצמו עם פיזיותרפיסט מוסמך (ההעדפה - אין בעיית רישוי).
- Datasets אקדמיים ציבוריים לפוזה בתרגילי כושר/שיקום: `MM-Fit`, `KIMORE` (עם 5 תרגילי שיקום מתויגים לפי נכונות), `UI-PRMD` (10 תרגילי שיקום מתועדים ב-Kinect עם ציון נכונות).
- Fitness3D / HuMMan (אם הרישוי מאפשר).

**מה מפיקים מהסרטון:**
1. שלד לכל פריים (אותו pipeline של המוצר → aligning מלא).
2. סדרת זמן של הזווית הרלוונטית (`knee_angle(t)`).
3. **חתימה** = סטטיסטיקות: min, max, mean, std, tempo (זמן ירידה/עלייה/עצירה), טווח שימוש (ROM utilization).
4. שמירת החתימה כ-JSON תחת `exercises/<name>/reference_signatures/*.json` + הפניה למקור וידאו.

**הרחבה:** לכל תרגיל, לפחות 3 חתימות (רקע גוף שונה, זווית מצלמה, קצב) כדי לא לקבע על "אדם אחד".

### 3.4 רגל 3 — וידאו קהילתי (YouTube / Instagram Reels)

**למה:** להרחיב את מגוון הגופים, זוויות המצלמה, ותנאי התאורה שהמוצר ראה. גם דוגמאות **שגויות** לתרגילים - הזהב לאימון מסווג "תקין/שגוי".

**כלים:**
- `yt-dlp` (כבר בשימוש בריפו הקיים - `yt-dlp>=2026.8.19`) - הורדת סרטונים ציבוריים.
- `instaloader` לפוסטים ציבוריים ב-Instagram (Reels, TV). **חובה: רק תוכן פומבי, ללא כניסה לחשבון.**
- שאילתות: `"squat proper form"`, `"lunge tutorial"`, `"physical therapy knee rehab"`, וכן `"squat wrong form"`, `"common mistakes squat"`.

**Pipeline של איסוף (רץ אוף-ליין ב-VM או בפעם אחת מקומית):**

```
       URL list
          │
          ▼
    yt-dlp / instaloader ──▶ mp4 files
          │
          ▼
    ffmpeg → frames at 15fps
          │
          ▼
    yolov8s-pose on each frame ──▶ per-frame keypoints
          │
          ▼
    filter: single-person, in-frame ≥85%, conf ≥0.5
          │
          ▼
    angle time-series + tempo + ROM per clip
          │
          ▼
    LLM (Anthropic) auto-tags clip:
      {exercise, correctness: good|nit|wrong,
       failure_mode: e.g. "knee valgus", body_side}
          │
          ▼
    Human-in-the-loop review (10% sample): קליק גס
          │
          ▼
    Feature store (SQLite/parquet) + video hashes for dedup
```

**מדיניות רישוי ופרטיות:**
- המערכת שומרת **רק פיצ'רים נגזרים** (זוויות, טמפו, תגיות) - לא את הוידאו המקורי.
- מטא-דאטה: `source_url`, `channel`, `retrieved_at`, `license_snapshot` (אם צוין).
- לא מפרסמים בחזרה את הסרטונים; משתמשים בהם כמו ב-fair-use אקדמי לחילוץ פיצ'רים.
- דגל התנגדות: אם יוצר תוכן דורש הסרה, `takedown_list.csv` מסיר את הפריטים מהאינדקס.

### 3.5 אינדוקס וקטורי — הצד הטכני של ה-RAG

**מבנה chunking לטקסט:**
- Chunk size: 512 tokens, overlap 64.
- לפני chunking: מבנה חלוקה סמנטי (Section → Paragraph → Chunk) כדי לא לקטוע באמצע משפט.
- כל chunk נושא: `chunk_id`, `text`, `title`, `section`, `source_id`, `license`, `tags[]`, `evidence_level`.

**מודל embeddings:**
- `all-MiniLM-L6-v2` (384-dim, ~90 MB, רץ על CPU) - ברירת מחדל, מיושר לתקציב 1 GB.
- שדרוג אופציונלי: `bge-small-en-v1.5` (512-dim, ~130 MB) לשיפור איכות ב-~5%.

**מסד וקטורי:**
- **ChromaDB** (persistent, ב-`~/data/chroma/` על ה-VM). קל, לא דורש שרת נפרד, יושב בתהליך.
- אלטרנטיבה שקולה: `Qdrant` (יותר כבד אך מהיר יותר).
- אינדקס נפרד לוידאו-פיצ'רים: `physiolive_evidence` (טקסט), `physiolive_signatures` (חתימות זוויות).

**Retrieval flow (בזמן משוב חי):**

```
event: "כפיפת ברך עמוקה מדי במהלך סקוואט"
   │
   ▼
Coach agent מייצר שאילתת חיפוש:
   "safe knee flexion depth during squat rehabilitation ACL"
   │
   ▼
embedding → top-8 chunks + top-3 signatures
   │
   ▼
LLM (בענן, Claude Haiku או Sonnet — עלות נמוכה)
מייצר משוב קצר בעברית, מבוסס בציטוט למקור
   │
   ▼
TTS מקומי משמיע: "ברך מגיעה עמוק מהמומלץ.
   מחקר X ממליץ על עצירה ב-90°."
   │
   ▼
דשבורד מציג את הציטוט + קישור למקור בטאב ה-Session
```

### 3.6 עדכון מתמשך של הידע

- **Cron ב-VM:** אחת לשבוע, מריץ הרחבה של הקורפוס — מוריד abstracts חדשים מ-PubMed בשאילתות מוגדרות (`"physical therapy"`, `"rehabilitation exercise"`), מוסיף לאינדקס.
- **גרסאות אינדקס:** `chroma_v1_2026_09_18/`, כך שסבב שחזור אפשרי בכל רגע.
- **Sanity tests:** 20 שאילתות "זהב" (עם top-1 known correct) שרצות אחרי כל עדכון — אם ה-recall יורד מתחת ל-90%, האינדקס לא מתקדם לפרודקשן.

---

## 4. מודלי למידת מכונה — מפרט מדויק

### 4.1 טבלת מודלים

| מודל | תפקיד | ריצה | גודל | מקור |
|---|---|---|---|---|
| **YOLOv8s-pose** (OpenVINO) | Pose estimation, 17 keypoints | לוקאלית ב-CPU | ~22 MB | Ultralytics, אותו זרם כמו הריפו הקיים |
| **MediaPipe Pose (Full)** | Fallback ל-pose, ~33 keypoints (מוסיף עמוד שדרה ופלג פנים) | לוקאלית | ~10 MB | Google (Apache-2.0) |
| **בונה זוויות + חוקים** | חישוב פר-פריים ל-6 זוויות + חוקי form | לוקאלית, numpy בלבד | 0 | קוד ידי |
| **Rep classifier** (custom) | Good / Nit / Wrong per rep, אימון על KIMORE + UI-PRMD + Scraped | לוקאלית, ONNX | ~4 MB | LightGBM/XGBoost על פיצ'רים מזווית |
| **all-MiniLM-L6-v2** | Text embeddings ל-RAG | VM (ChromaDB) | ~90 MB | sentence-transformers (Apache-2.0) |
| **Whisper tiny** (אופציונלי) | STT — למשל "התחל", "השהה" קולית | לוקאלית | ~40 MB | OpenAI (MIT) |
| **pyttsx3** | TTS מקומי, עברית + אנגלית | לוקאלית | 0 | pyttsx3 |
| **LLM ענן** (Claude Sonnet 4.5 / Haiku 4.5) | ניסוח משוב מבוסס-RAG, סיכום סשן | ענן דרך HTTPS | 0 | Anthropic API |
| **Sound event detector** (YAMNet קטן) | לזהות "האח!" או קול כאב — התראה | לוקאלית, אופציונלי | ~4 MB | Google |

### 4.2 החלטות עיצוב חשובות

**A. יריב שאלת "למה שני מודלי pose?"**
YOLOv8s-pose מהיר וטוב לרוב המקרים; MediaPipe מוסיף לנו נקודות עמוד שדרה שקריטיות לתרגילי גב (Cat-Cow, Pelvic-Tilt). המערכת בוחרת אוטומטית לפי סוג התרגיל (`exercise.json` שדה `pose_backend: "yolo" | "mediapipe"`).

**B. אימון Rep-classifier — הזרם**

```
Dataset:
  KIMORE (5 rehab exercises × ~30 subjects × 3 correctness classes)
  UI-PRMD (10 exercises × 10 subjects × 2 classes)
  Scraped YouTube (auto-tagged, human sample-reviewed)
  Own recordings (5-20 clips per exercise)

Features (per rep):
  - angle_min, angle_max, ROM
  - eccentric_time, concentric_time, hold_time
  - symmetry_index (L vs R)
  - jerk (numerical derivative of angle)
  - shoulder-hip alignment stddev
  - knee-toe horizontal offset

Model:
  LightGBM (gbdt, 200 trees, depth 6)
  Export → ONNX
  Latency target < 5 ms per rep

Evaluation:
  Stratified 5-fold on subjects (not on reps — leak-proof)
  Metric: Macro-F1
  Target: ≥ 0.80 on KIMORE, ≥ 0.75 on UI-PRMD
```

**C. LLM בענן — למה לא לוקאלי?**
- Llama-3-8B לוקאלי דורש 8+ GB VRAM או ~5 GB RAM עם quantization; לא לפי תקציב Chromebook / VM 1GB.
- Claude Haiku 4.5 באמצעות API: השהיה ~700ms לתשובה קצרה, עלות זניחה (חלקי סנט לסשן), איכות עברית מצוינת.
- כל קריאת LLM נשמרת עם ה-prompt וה-response באוף-ליין (למקרה של debugging).

**D. פרטיות פנייה ל-LLM:**
- אין העלאת וידאו או פריים.
- נשלחת רק תמצית טקסטואלית: `{exercise: "squat", angle_min: 45, angle_max: 170, ROM_util: 0.68, top_chunks: [c1, c2, c3]}`.
- הפרומפט מפורש: "תן משוב קצר בעברית של 1-2 משפטים, מבוסס על הצ'אנקים המצוטטים למטה."

### 4.3 עקומת שיפור המודלים לאורך זמן

| חודש | דאטה | מטרה |
|---|---|---|
| 1 | KIMORE + UI-PRMD | MVP: 5 תרגילים, F1 > 0.75 |
| 2 | +200 סרטוני YouTube auto-tagged | +5 תרגילים, F1 > 0.80 |
| 3 | +500 סרטונים + human review of 10% | תיקון failure modes, F1 > 0.85 |
| 4-6 | דאטה ממטופלים אמיתיים (opt-in) | התאמה אישית, personalization layer |

---

## 5. הנחיות למטופל (Patient Guidance Layer)

הנחיות בפועל שהמערכת מציגה למטופל — מסודרות לפי שלב.

### 5.1 לפני הסשן — Setup Wizard

1. **מיקום מצלמה:**
   - גובה: קו המותן (כ-1.0 מ' מהרצפה).
   - מרחק: 2.0-2.5 מ' מהמשתמש.
   - זווית: לפי תרגיל — פרונטלי לסקוואט, פרופיל לאנג'.
   - המערכת מציגה **סימולציית התצוגה הצפויה** (איור סכמטי) + סטריפ live מהמצלמה עם overlay של הגבולות המומלצים.

2. **תאורה:**
   - מקור אור מלפנים או מהצד — לא מאחור.
   - זיהוי אוטומטי: אם ממוצע הבהירות < 60/255 → הודעה "הדלק אור."
   - אם contra-jour (חלון מאחור) — המצלמה תצלם צללית; המערכת מזהה ומזעיקה.

3. **בגדים:**
   - מכנס צמוד (או ספורט) לזיהוי ברכיים; לא מכנסי טוגה.
   - חולצה שאינה משתלשלת על המותן.

4. **מרחב:**
   - 2 מ' × 2 מ' ריק ליד המשתמש (בטיחות בעיקר לתרגילי איזון).

5. **בטיחות אישית:**
   - שאלון קצר בפעם ראשונה: פציעה פעילה? כאב פרק? — במקרים אדומים המערכת ממליצה לא לתרגל ומפנה לפיזיותרפיסט.

### 5.2 קליברציה אישית (חד-פעמית לכל תרגיל)

1. המערכת: "בצע חזרה איטית אחת בטווח שנוח לך."
2. המערכת מודדת את הזווית המקסימלית והמינימלית שלך = **הטווח שלך (100%)**.
3. יעדים בסשן מבוססים על אחוז מהטווח הזה, לא על סף מוחלט (חשוב למטופלי שיקום — 90° לברך של אדם בריא זה לא 90° לברך פוסט-ניתוח).
4. ניתן לעדכן קליברציה בכל התחלת סשן.

### 5.3 במהלך התרגיל

- **HUD גדול:** שם תרגיל, מונה חזרות (`7 / 12`), אינדיקטור צבע (ירוק/צהוב/אדום), זווית עדכנית.
- **קול:** משוב קצר בסוף כל חזרה: "יופי" / "ירידה מעט עמוקה" / "ברך פנימה — יישר." לא באמצע החזרה — לא לבלבל.
- **התראות בטיחות (עוברות מעל כל השאר):**
   - זיהוי נפילה חשודה → קול חזק "עצור."
   - קול צעקת כאב (אם Whisper דולק) → הפסקת הסשן, שמירת פריים ל-Session.

### 5.4 בין חזרות ובין סטים

- ספירת מנוחה (`0:30`) בעברית.
- טיפ מהיר מה-RAG: "עצור 30 שנ' לפני הסט הבא — הזמן מאפשר להסיר את חומצת החלב מהשריר."

### 5.5 אחרי הסשן

- מסך סיכום: אחוז חזרות תקינות, ROM ממוצע, סימטריה, שינוי מהסשן הקודם.
- 3 טיפים מותאמים (מבוססי RAG) לסשן הבא.
- כפתור "שלח לפיזיותרפיסט" — מייצר PDF קצר עם הגרפים והתגיות (בלי וידאו).

### 5.6 עקרונות תוכן ההנחיה

- **קצר.** משפט אחד, לא רשימת bullets.
- **חיובי לפני שלילי.** "יופי — בפעם הבאה נסה גב יותר ישר" ולא "הגב שלך עקום."
- **מבוסס מקור.** בטאב ה-Session ניתן ללחוץ על הודעה כדי לראות את הצ'אנק מ-PubMed שהוביל אליה.
- **דו-לשוני:** עברית וגם אנגלית (בחירת המשתמש), TTS ב-2 השפות.
- **הימנעות מתפקיד רופא:** אף פעם לא "יש לך פציעת ACL", תמיד "התבנית מזכירה מקרים של ACL — פנה לפיזיותרפיסט."

---

## 6. מקור זרמת הווידאו

תמיכה בשני מקורות ראשיים + מקור שלישי (סרטון מוקלט לרפרנס/דמו).

### 6.1 מצלמת לפטופ מובנית (Primary)

- `cv2.VideoCapture(0)`, 30 fps, 640×480 או 1280×720.
- יתרונות: פשוט, אין latency רשת, לא דורש שום התקנה.
- חסרונות: זווית לפעמים לא אידיאלית (המשתמש חייב לרחוק 2 מ').

### 6.2 מצלמת סמארטפון (Secondary — משודרג בעדיפות בעולם השיקום)

**למה זה חשוב:** סמארטפון = מצלמה טובה יותר + חצובה זמינה + זווית גמישה. עבור תרגילי רצפה (leg raise, glute bridge) זו יתרון מכריע.

**מנגנון:**
- אפליקציית **IP Webcam** (Android) או **DroidCam** (iOS/Android) - חינמיות, פתוחות.
- הטלפון פותח שרת RTSP או MJPEG: `http://<phone-ip>:8080/video`.
- ב-notebook, המשתמש בוחר מקור: `Camera 0` / `Camera 1` / `Phone (URL)`.
- `cv2.VideoCapture("http://192.168.1.42:8080/video")` — עובד one-to-one עם הקוד הקיים.
- Handshake בהתחלה: המערכת מודדת latency, אם > 300ms → אזהרה למשתמש שיעבור ל-Wi-Fi 5GHz או USB tethering.

**בנוסף:** התקנה אחת של אפליקציית **PhysioLive Companion** (PWA שיכולה להיווצר בעתיד) — יותר חלק, אבל לא לפני MVP.

### 6.3 סרטון מוקלט (Tertiary)

- טעינת `.mp4` — לתרגול offline, לרפרנס של הפיזיותרפיסט, ל-QA של המפתחים.
- אותו pipeline; רק המקור משתנה.

### 6.4 טבלת החלטת מקור

| תרגיל | מקור מומלץ | סיבה |
|---|---|---|
| Squat, Lunge, Warrior | לפטופ (פרונט) | פשטות |
| Leg Raise (שכיבה) | סמארטפון (side view) | הלפטופ לא רואה טוב את הרגל בגובה הרצפה |
| Glute Bridge | סמארטפון (side view) | אותו סיבוב |
| Shoulder Rotation | לפטופ (פרונט) | חצי גוף עליון בלבד |
| Cat-Cow, Pelvic-Tilt | סמארטפון (side view) | קריטי לראות עמוד שדרה בפרופיל |

---

## 7. סוכני AI — שכבת האורקסטרציה

**עיקרון:** לא סוכן ענק אחד עם 20 כלים. **4 סוכנים ממוקדים**, כל אחד עם אחריות אחת, שמדברים ביניהם ב-message bus קטן.

### 7.1 מפת סוכנים

```
              ┌───────────────────────────────┐
              │       Session Orchestrator    │
              │  (state machine, לא LLM)      │
              └───────┬───────────────────────┘
                      │
     ┌────────────────┼────────────────┬────────────────┐
     ▼                ▼                ▼                ▼
┌──────────┐   ┌────────────┐   ┌──────────────┐   ┌────────────┐
│ Coach    │   │ Analyzer   │   │ Progress     │   │ Curator    │
│ agent    │   │ agent      │   │ agent        │   │ agent      │
├──────────┤   ├────────────┤   ├──────────────┤   ├────────────┤
│ חזון: כמו│   │ קורא זוויות│   │ מסתכל על     │   │ רץ ב-VM,    │
│ פיזיו   │   │ + חוקים,   │   │ היסטוריה,    │   │ מרחיב את    │
│ מדבר עם  │   │ מייצר      │   │ מזהה מגמות,  │   │ ה-KB, מתייג │
│ מטופל.   │   │ verdict per│   │ ממליץ על     │   │ סרטונים,    │
│ יוצר     │   │ rep + סיבה.│   │ פרוטוקול     │   │ ומרחיב את   │
│ שאילתות  │   │            │   │ עתידי.       │   │ signatures. │
│ ל-RAG    │   │            │   │              │   │            │
│ ומנסח    │   │            │   │              │   │            │
│ משוב.    │   │            │   │              │   │            │
└──────────┘   └────────────┘   └──────────────┘   └────────────┘
     │              │                  │                 │
     └──────────────┴──────────────────┘                 │
                    │                                    │
                    ▼                                    ▼
              ┌─────────────┐                     ┌──────────────┐
              │ RAG / Vector│◀════════════════════│ Web scrape,  │
              │ store       │                     │ PubMed API   │
              └─────────────┘                     └──────────────┘
```

### 7.2 פירוט הסוכנים

**A. Coach Agent (LLM — Claude Haiku/Sonnet)**
- **Trigger:** אירוע "rep סיים" או "אירוע בטיחות" מה-Analyzer.
- **Input:** `{exercise, rep_verdict, top_features, top_rag_chunks}`.
- **Output:** משפט אחד בעברית + מקור.
- **פרומפט מערכת:** "אתה פיזיותרפיסט וירטואלי. תן משפט אחד קצר, חם, מבוסס-ראיות. ציין את המקור בסוגריים."
- **Rate limit:** לכל היותר קריאה אחת ל-3 שניות (debounce נוסף מעל).

**B. Analyzer Agent (Rules + LightGBM, ללא LLM)**
- **Trigger:** כל פריים.
- **Input:** keypoints, exercise config, calibration.
- **Output:** angle features + verdict + failure_mode.
- **Latency target:** < 10ms.
- **Why not LLM:** מהירות, דטרמיניזם, אין עלות ענן.

**C. Progress Agent (Rules + LLM נדיר)**
- **Trigger:** סוף סשן.
- **Input:** לוג הסשן + היסטוריה מקומית (SQLite).
- **Output:** דוח סיכום, השוואות, המלצה ל-3 תרגילים מוצעים מחר.
- **מפעיל LLM פעם אחת בסוף** — לניסוח הסיכום.

**D. Curator Agent (רץ ב-VM, שיטתי, לא real-time)**
- **Trigger:** cron יומי / שבועי.
- **Input:** רשימת שאילתות YouTube/PubMed + מצב האינדקס.
- **Output:** אינדקס מעודכן + מטריקות איכות.
- **מפעיל LLM לתיוג auto** של סרטונים חדשים (10-100 קריאות בסבב).
- **Human-in-the-loop:** דוח שבועי במייל עם 20 פריטים לסקירה ידנית.

### 7.3 Bus תקשורת

- לוקאלי: FastAPI + `asyncio.Queue` בתוך אותו תהליך.
- VM: HTTP calls בין המחברת המקומית לשירותי ה-VM (Analyzer/Progress אצל המשתמש; RAG/Curator ב-VM).

### 7.4 עקרונות "סוכן טוב"

1. **אחריות אחת.** כל סוכן עונה לשאלה אחת.
2. **דטרמיניזם קודם.** רק אחרי שכל החוקים מוצו, מגיעים ל-LLM.
3. **פרומפט חתום.** לכל סוכן system prompt קבוע בגרסה (semver), נשמר בגיט.
4. **Trace.** כל הפעלת סוכן נכתבת ל-`traces/session_<id>/<agent>_<ts>.json` — ניתן לשחזר את כל הסשן.

---

## 8. Google Cloud e2-micro VM — התשתית החינמית

**מכונה:** e2-micro (2 vCPU burstable, 1 GB RAM, 30 GB standard PD) — במסלול Free Tier של GCP (חינם כל עוד השימוש בתחומי הקצאה).

### 8.1 מה **רץ** על ה-VM?

| שירות | סיבה שהוא ב-VM ולא לוקאלי | RAM |
|---|---|---|
| **RAG Service (FastAPI + ChromaDB)** | אינדקס גדול (~500 MB), משותף לכל המשתמשים, לא רוצים להוריד אותו לכל לפטופ | ~350 MB |
| **Curator (cron scheduler + workers)** | רצים 24/7 בלי לתפוס משאבים במחשב | ~150 MB (בזמן ריצה בלבד) |
| **Session Backup API** | סשנים של משתמשים (אופציונלי, opt-in) — sync בין מכשירים | ~50 MB |
| **Public health/status endpoint** | לניטור | זניח |
| **nginx reverse proxy + TLS** | Let's Encrypt, hostname stable | ~20 MB |

**סה"כ תקציב RAM בשגרה: ~570 MB. שאר 430 MB חיץ.**

### 8.2 מה **לא** רץ ב-VM?

- Pose estimation — ב-CPU של הלפטופ.
- Angle rules + Analyzer — לוקאלית.
- TTS — לוקאלית (pyttsx3).
- Dashboard — לוקאלית (המשתמש פותח localhost:8000).

הסיבה: latency. inference של pose חייב להיות קרוב למצלמה. VM זה למה שיכול לחיות עם 300ms round-trip.

### 8.3 חלוקת המודלים לפי מיקום

```
        LOCAL (laptop)                    CLOUD (e2-micro VM)
     ┌──────────────────┐              ┌──────────────────────┐
     │ YOLOv8s-pose     │              │ ChromaDB persistent  │
     │ MediaPipe        │              │ all-MiniLM-L6-v2     │
     │ Rules engine     │              │ Curator jobs         │
     │ Rep classifier   │              │ PubMed sync          │
     │ TTS pyttsx3      │              │ YouTube scrape queue │
     │ Whisper tiny     │◀───HTTPS────▶│ Session backup       │
     │ Dashboard        │              │                      │
     │ Local SQLite     │              │ FastAPI + nginx      │
     └──────────────────┘              └──────────────────────┘
```

### 8.4 API של ה-VM (מה המחברת קוראת)

```
POST /rag/query
  body: {"query": "...", "top_k": 5, "filters": {...}}
  resp: {"chunks": [{text, source, score}], "latency_ms": 45}

POST /coach/feedback
  body: {"exercise": "squat", "features": {...}, "top_chunks": [...]}
  resp: {"message_he": "...", "message_en": "...", "source_urls": [...]}
  # ה-VM קורא ל-Anthropic API בשם המשתמש עם המפתח שלו.

POST /session/backup
  body: {"session_id": "...", "log": {...}}
  resp: {"ok": true, "cloud_id": "..."}

GET /health
  resp: {"status": "ok", "index_version": "v1_2026_09_18",
         "chunks_count": 42137, "signatures_count": 130}
```

### 8.5 אבטחה ופרטיות

- **מפתח API אישי (Bearer token)** נוצר בפעם הראשונה שהמשתמש מפעיל את המחברת ונשמר ב-`~/.physiolive/config.json`.
- **TLS** דרך Let's Encrypt + nginx — התעבורה מוצפנת.
- **rate limit** ב-nginx: 10 בקשות/דקה למשתמש. אין spam.
- **אין וידאו על ה-VM.** אף פעם. רק פיצ'רים ותגיות.
- **rate-limited scraping:** Curator עומד בהנחיות `robots.txt` ו-throttle של 1 בקשה/2 שניות.

### 8.6 שלבי הקמת ה-VM (Runbook)

1. יצירת פרויקט חדש ב-GCP → הפעלת Free Tier.
2. `gcloud compute instances create physiolive-vm --machine-type=e2-micro --zone=us-central1-a --image-family=debian-12`.
3. פתיחת פורט 443 בלבד ל-Internet, 22 מוגבל ל-IP האישי.
4. התקנה: Python 3.11 + FastAPI + ChromaDB + nginx + certbot.
5. `git clone` של הריפו → `pip install -r requirements-vm.txt`.
6. `systemd service` ל-`rag-service.service` + `curator.service`.
7. `certbot --nginx -d physiolive.<subdomain>.<domain>` — TLS אוטומטי.
8. אתחול מלא ובדיקת `/health`.
9. Backup יומי של `~/data/chroma` ל-GCS Bucket (חינם עד 5 GB).

### 8.7 עלויות צפויות

| רכיב | עלות/חודש |
|---|---|
| e2-micro (Free Tier, us-central1) | $0 |
| 30 GB PD-standard | $0 (בתוך free tier) |
| Egress < 1 GB/חודש | $0 |
| GCS Bucket 5 GB | $0 |
| Anthropic API (Claude Haiku) — ~100 סשנים | ~$1-2 |
| **סה"כ** | **~$1-2/חודש** |

---

## 9. אדריכלות משולבת (End-to-End)

```
                          ┌──────────────────────────────────┐
                          │       Local (User Laptop)        │
┌──────────┐              │                                  │
│ Webcam / │──── frame ──▶│  YOLOv8s-pose (OpenVINO CPU)     │
│ Phone    │              │        │                         │
│ RTSP     │              │        ▼                         │
└──────────┘              │  Angle calc + Form rules         │
                          │        │                         │
                          │        ▼                         │
                          │  Rep classifier (LightGBM ONNX)  │
                          │        │                         │
                          │        ▼                         │
                          │  Verdict + failure_mode          │
                          │        │                         │
                          │        ▼                         │
                          │  ┌───────────────┐               │
                          │  │ Coach agent   │───HTTPS──┐    │
                          │  └───────────────┘          │    │
                          │        │                    │    │
                          │        ▼                    │    │
                          │  ┌───────────────┐          │    │
                          │  │ TTS (pyttsx3) │          │    │
                          │  └───────────────┘          │    │
                          │        │                    │    │
                          │        ▼                    │    │
                          │  Dashboard (localhost:8000) │    │
                          │        │                    │    │
                          │        ▼                    │    │
                          │  Local SQLite               │    │
                          └────────┬────────────────────┘    │
                                   │                         │
                                   ▼                         │
                          ┌──────────────────────────────────┘
                          │
                          ▼
             ┌──────────────────────────────────────┐
             │       Cloud (e2-micro VM, GCP)       │
             │                                      │
             │  nginx (TLS) ──▶ FastAPI             │
             │                     │                │
             │      ┌──────────────┼──────────────┐ │
             │      ▼              ▼              ▼ │
             │  /rag/query   /coach/feedback  /session/backup
             │      │              │                │
             │      ▼              ▼                │
             │  ChromaDB      Anthropic API         │
             │  + Embed       (Claude Haiku)        │
             │      ▲                               │
             │      │                               │
             │  Curator agent (cron):               │
             │    PubMed sync                       │
             │    YouTube/Insta scrape              │
             │    LLM auto-tag                      │
             │    Human review queue                │
             └──────────────────────────────────────┘
```

---

## 10. מבנה תיקיות מוצע

```
physiolive/
├── physio_live.ipynb              # המחברת הראשית (Run All)
├── requirements.txt               # תלויות לוקאליות
├── requirements-vm.txt            # תלויות לצד השרת
├── README.md                      # מבוסס תבנית הריפו הקיים
├── media/                         # screenshots של הדשבורד
├── src/
│   ├── app/
│   │   ├── pose_gate.py           # sensitivities מפוזה
│   │   ├── angles.py              # 6 זוויות, HUD יעד
│   │   ├── exercises/             # JSON פר-תרגיל
│   │   │   ├── squat.json
│   │   │   ├── lunge.json
│   │   │   ├── leg_raise.json
│   │   │   └── ...
│   │   ├── rep_counter.py         # ROM-gate + 2-tick
│   │   ├── form_rules.py          # מנוע חוקים
│   │   ├── rep_classifier.py      # ONNX inference
│   │   ├── tempo.py               # תזמון חזרה
│   │   ├── balance.py             # יציבות (חשד לנפילה)
│   │   ├── voice.py               # pyttsx3 + queue
│   │   ├── session_log.py         # SQLite persistence
│   │   ├── dashboard_server.py    # שרת מקומי
│   │   ├── phone_stream.py        # ניהול RTSP/MJPEG
│   │   └── agents/
│   │       ├── coach.py           # קליינט ל-VM /coach
│   │       ├── analyzer.py        # לוקאלי, ללא LLM
│   │       └── progress.py        # סיכום סוף-סשן
│   ├── web/                       # דשבורד frontend
│   │   ├── index.html
│   │   ├── app.js
│   │   └── snapshots/
│   └── vm/                        # קוד לצד הענן (רץ ב-e2-micro)
│       ├── rag_service.py         # FastAPI + ChromaDB
│       ├── curator/
│       │   ├── pubmed_sync.py
│       │   ├── youtube_scrape.py
│       │   ├── instagram_scrape.py
│       │   ├── auto_tagger.py     # LLM auto-tag
│       │   └── signature_builder.py
│       ├── coach_bridge.py        # פרוקסי ל-Anthropic
│       └── deploy/
│           ├── nginx.conf
│           ├── systemd/*.service
│           └── setup.sh
├── data/                          # לא נכנס לגיט
│   ├── reference_signatures/      # חתימות זוויות
│   ├── chroma_v1/                 # מקומי לפיתוח
│   └── sessions/                  # לוגי סשן מקומיים
└── docs/
    ├── product_spec.md            # המסמך הזה
    ├── model_card_rep_clf.md      # קלף מודל לclassifier
    ├── data_lineage.md            # מקורות דאטה + רישוי
    └── privacy_policy.md
```

---

## 11. אבני דרך למימוש

| Milestone | תוכן | סטטוס לצאת | משך משוער |
|---|---|---|---|
| **M0 — Setup** | ריפו חדש, VM עולה, `/health` מחזיר `ok` | סביבת ריצה | 2-3 ימים |
| **M1 — Local Skeleton** | pose חי מ-webcam, HUD בסיסי, angle calc | דמו על הלפטופ | 3-4 ימים |
| **M2 — Squat MVP** | squat.json + rep counter + form rule ראשון + TTS | תרגיל אחד עובד מ-A ל-Z | שבוע |
| **M3 — RAG כבר תוכן** | Corpus scientific v1 (500 abstracts) עולה ל-Chroma; RAG endpoint מחזיר chunks | חיפוש טקסטואלי עובד | שבוע |
| **M4 — Coach agent** | Claude API מנוסח משוב עם ציטוט; מחליף רשימת מחרוזות סטטיות | משוב חי מבוסס מקור | 4 ימים |
| **M5 — 5 תרגילים + Rep classifier** | KIMORE + UI-PRMD אומן, ONNX ב-inference | 5 תרגילים איכותיים | שבועיים |
| **M6 — Session + Progress** | SQLite, Progress tab, סיכום סוף-סשן | Persistence מלא | שבוע |
| **M7 — Phone stream** | RTSP/MJPEG משמאל של המצלמה, חצי מהתרגילים ב-side view | תמיכה בסמארטפון | 3-4 ימים |
| **M8 — Curator YouTube** | scrape 500 סרטונים, auto-tag, אינדקס signatures מורחב | KB חי, גדל | שבועיים |
| **M9 — Personalization** | קליברציה אישית מלאה, יעדים לפי המשתמש | מטופל אמיתי יכול לתרגל שיקום | שבוע |
| **M10 — Polish + docs** | README כמו הריפו הנוכחי, gallery, model cards | מוכן לשיתוף | שבוע |

**סה"כ:** ~10-12 שבועות (2.5-3 חודשים) עבור מפתח יחיד.

---

## 12. מדדי הצלחה — Product KPIs

| מדד | יעד |
|---|---|
| FPS על CPU (i5, 2019) | ≥ 15 |
| Latency פוזה→ציור | ≤ 100 ms |
| Latency קול משוב | ≤ 500 ms |
| Latency RAG query | ≤ 300 ms (VM us-central) |
| Latency Coach feedback (LLM) | ≤ 1500 ms end-to-end |
| דיוק ספירת חזרות | ≥ 95% מול ספירה ידנית |
| Rep classifier Macro-F1 | ≥ 0.80 על holdout |
| False alarms per session (form) | ≤ 2 |
| KB coverage — שאילתות עם top-1 רלוונטי | ≥ 90% |
| Cost / user / month | ≤ $0.05 |
| Install to first rep | ≤ 5 min |

---

## 13. סיכונים ומיתיגציה

| סיכון | מיתיגציה |
|---|---|
| **כשל רפואי:** מטופל מפעיל את המערכת עם פציעה חמורה | Screening בשאלון הפתיחה, אזהרה מפורשת "כלי עזר, לא תחליף לרופא" |
| **LLM ממציא ציטוט** | Coach אף פעם לא מנסח בלי צ'אנקים; פרומפט מפורש "ציין רק מקורות מהרשימה למטה, אם אין - אמור 'אין מקור'" |
| **גישה לא חוקית לסרטונים** | Curator בודק רישוי; שמירת פיצ'רים בלבד; takedown workflow |
| **VM 1 GB מתמלא** | swap 2 GB על ה-disk; monitoring; אם הצומת הופך צפוף — הגירה ל-e2-small (~$6/חודש) |
| **פרטיות המשתמש** | כל דבר לוקאלי by default; opt-in ל-cloud backup |
| **המצלמה גרועה או בזווית לא נכונה** | Setup wizard חכם, בדיקת conf ממוצע לפני התחלה |
| **תלות באינטרנט** | Fallback ל-cached RAG results + מנוע חוקים לוקאלי — הכל חוץ מ-Coach agent (הטקסט המנוסח) עובד offline |
| **התראה שווא של נפילה** | 2-tick + סף גבוה + עדיף להזהיר מאשר להחמיץ; המשתמש יכול לבטל |
| **דיסק ה-VM נמחק** | Backup יומי ל-GCS; אינדקס ניתן לשחזור מ-scratch תוך 4-6 שעות |

---

## 14. משפט אתי ורישוי

- **המוצר איננו התקן רפואי (medical device).** התיוג המפורש: "General wellness — informational."
- אין אחסון מזהים אישיים (PII) בענן ללא הסכמה מפורשת.
- **דיסקליימר** מוצג בפעם הראשונה: "כלי עזר לתרגול; אינו מחליף אבחון או טיפול של איש מקצוע."
- קוד המוצר: MIT או Apache-2.0. מודלי YOLO ב-AGPL-3.0 (זהה לריפו הקיים) — נדרש להשאיר את הריפו פתוח או להחליף למודל pose בעל רישוי מרוכך (MediaPipe בלבד) בגרסה מסחרית.
- כל מקור נתונים (חוץ מ-Anthropic API שהוא שירות בתשלום) — פתוח, בציטוט, בעם `license` בכל chunk.

---

## 15. מה **לא** נכנס למוצר ב-MVP (ומדוע)

- **RAG-based chatbot כללי כמו PhysioVision** — לא ב-MVP. הצ'אט משעה את התרגיל; משוב מותאם-לחזרה חשוב יותר.
- **תמיכה במטופלים ילדים / קשישים** — המודלים אומנו על מבוגרים; יידרש דאטה נוסף.
- **גרסת iOS/Android native** — לא ב-MVP. PWA אולי אחרי M8.
- **שיתוף בין-מטופלים / social** — לא נחוץ בשלב הזה, מוסיף מורכבות פרטיות.
- **Payment / subscription** — MVP חינם, קוד פתוח.
- **תרגילי כוח כבד (Deadlift, Bench)** — סיכון בטיחות גבוה; דורש פיזיותרפיסט מלווה.

---

## 16. סיכום שורה אחת

**PhysioLive** = הליבה של הריפו הקיים (pose, HUD, snapshots, notebook-first) + **מוח מדעי (RAG על קורפוס אמיתי + חתימות זוויות מדאטה מוקצע/ציבורי) שגר בענן** + **4 סוכני AI ממוקדים** + **תמיכה במצלמת סמארטפון** + **VM חינמית של 1 GB שעושה את העבודה השחורה 24/7**. מחברת אחת. מטופל אחד. משוב שמתייחס למקור.

---

*מסמך זה מהווה אפיון מקדים לאישור. אין בו הבטחה טכנית סופית; מפרטי הביצועים והרישוי ייבחנו שוב בסוף כל Milestone.*
