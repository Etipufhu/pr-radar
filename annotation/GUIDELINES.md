# Annotation guidelines / Etiketleme yönergeleri — FOREO-domain DimABSA v1

**Short version:** read the headline, look at the proposed labels, ask yourself
*"does this feel right?"* and move the sliders if it doesn't. That is the whole job.

**Kısa özet:** başlığı oku, önerilen etiketlere bak, kendine *"bu bana doğru geliyor mu?"*
diye sor; gelmiyorsa kaydırıcıları oynat. İşin tamamı bu.

---

## Türkçe

### Neden sen? (Uzman olmana gerek yok)

DimABSA veri setindeki valence/arousal değerleri dilbilimcilerden değil, **sıradan
okuyuculardan** gelir: birkaç kişi aynı cümleye sezgisel bir puan verir, puanların
ortalaması alınır (veride `7.83`, `6.38` gibi değerlerin görülmesinin sebebi budur).
Yani istenen şey tam olarak senin sıradan, dürüst insan yargın. "Doğru cevap" yoktur;
makul bir okuyucunun hissettiği vardır. Emin olmadığında ilk izlenimine güven ve devam et.

### Neyi etiketliyoruz?

Her kayıt bir haber başlığıdır. İçinde bir veya birkaç **aspect** (yön) vardır:
başlığın hakkında bir şey söylediği hedef.

| Alan | Anlamı | Örnek |
|---|---|---|
| **Aspect** | Başlıkta *aynen geçen* hedef ifade. Başlıkta yoksa `NULL`. | `Foreo Luna 5 LED`, `Black Friday deals`, `LED masks` |
| **Opinion** | Hedef hakkında yargı bildiren ifade, başlıkta aynen geçer. Yoksa `NULL`. | `best`, `misleading`, `20% off` |
| **Category** | `VARLIK#ÖZELLİK` (listesi aşağıda) | `PRODUCT#PRICES` |
| **Brand** | Aspect hangi markaya ait | `foreo`, `therabody`, `generic` … |
| **Valence (V)** | Olumsuz ↔ olumlu, 1.00–9.00 | 1 = çok olumsuz, 5 = nötr, 9 = çok olumlu |
| **Arousal (A)** | Sakin ↔ heyecanlı/yoğun, 1.00–9.00 | 1 = sakin/olgusal, 9 = çok yoğun |

**Valence** başlığın o hedef için ne kadar iyi/kötü bir şey söylediğidir.
**Arousal** ise yönden bağımsız olarak *ne kadar yoğun/heyecanlı* söylediğidir:
bir geri çağırma (recall) haberi olumsuzdur **ve** oldukça yoğundur; "en iyi 7 masaj
tabancası" olumludur ama sakindir.

### Ölçek çapaları (bu setten gerçek örnekler)

**Valence**

| V | Ne zaman | Örnek başlık (öneri) |
|---|---|---|
| 1–2 | Felaket, skandal, ciddi güvenlik sorunu | `Therabody Recalls … Charger` → 2.25 |
| 2–3 | Açık olumsuz uyarı | `Government urged to tackle misleading LED face masks` → 2.25 |
| 3–4 | Belirgin bir kusur | `one feature annoyed me` → 3.25; `big and ungainly` → 3.5 |
| 5 | Nötr / olgusal / karar yok / açık soru | `How Do They Stack Up to the Therabody JetBoots?` → 5.0 |
| 6 | Hafif olumlu: lansman, ortaklık, listeye girmek | `FOREO lanza su primer calendario de Adviento` → 6.25 |
| 7 | Açık olumlu: "en iyi", indirim | `7 Best Massage Guns` → 7.25; `20% off` → 7.25 |
| 8 | Çok olumlu, süperlatif | `This New Launch Tops Them All` → 8.25 |
| 9 | Coşkulu, sınırsız övgü (başlıklarda nadir) | "the best thing I've ever used, life-changing!" |

**Arousal**

| A | Ne zaman | Örnek |
|---|---|---|
| 1–3 | Tamamen kuru, teknik (başlıklarda nadir) | bir yönetmelik maddesi |
| 4 | Olgusal kurumsal haber | Therabody'nin KEN5.GOLF ile ortaklık anlaşması (Japonca) → 4.0 |
| 5 | Bilgilendirici liste/rehber | `Best red light therapy masks of 2026` → 5.75 |
| 6–7 | İndirim heyecanı, ünlem, "viral" | `Black Friday sale is LIVE` → 7.25 |
| 8 | Çok yoğun: "şok edici", "açık ara en etkileyici" | `Results Are “Shocking”` → 8.0 |
| 9 | Aşırı duygusal, büyük harfli çığlık | — |

Pratik ipucu: V 5'ten ne kadar uzaksa A genelde o kadar yüksektir (DimABSA verisinde de
böyle). Ama zorunlu değil: sakin bir "en iyi liste" V 7, A 5.5 olabilir.

### Kategoriler

Varlık: `BRAND` (markanın kendisi: indirim kampanyası, satın alma, sponsorluk) veya
`PRODUCT` (belirli bir cihaz ya da ürün kategorisi).
Özellik: `GENERAL`, `PRICES` (fiyat, indirim, kampanya), `QUALITY` ("en iyi", test
birincisi), `PERFORMANCE` (sonuç/etki), `DESIGN_FEATURES`, `USABILITY`, `POPULARITY`
(viral, ünlü kullanıyor, çok satan), `SAFETY` (geri çağırma, yanıltıcı iddia),
`BUSINESS` (satın alma, ortaklık, yatırım).

### Brand alanı

- `foreo`, `nuface`, `currentbody`, `therabody`, `pmd`, `solawave`: takip edilen markalar.
- `other`: adı geçen ama takip etmediğimiz marka/mağaza (Medicube, Amazon, Hyperice).
- `generic`: ürün kategorisi, marka yok ("LED masks", "massage guns").
- `unknown`: belli bir ürün ama başlık hangi markanın olduğunu söylemiyor.
- `BrandInText = false`: marka başlıkta geçmiyor, haberin kendisinden (arama sorgusundan)
  geliyor. Bunları özellikle kontrol et.

### Ne zaman Skip?

Başlıkta güzellik teknolojisiyle ilgili değerlendirilebilir bir hedef yoksa (ör. #113
"Public Transportation…") ya da başlığı hiç anlamıyorsan **Skip**. Skip bir hata değildir.

### İş akışı (~45 dk)

1. Önce düşük güvenli (`low`) kayıtlar gelir (21 tane); bunlara biraz daha zaman ayır.
2. Geri kalanlar için: doğru görünüyorsa **Accept** (kayıt başına ~10–15 sn).
3. Bir değer ~1 puandan fazla yanlış geliyorsa kaydırıcıyı oynat ve **Save fix**.
   0.25–0.5'lik farklar için uğraşma; ortalama zaten gürültülüdür.
4. Aspect/opinion metni yanlışsa düzelt (başlıkta *aynen* geçmesi gerekir).
5. Her tıklama otomatik kaydedilir; istediğin an kapatıp sonra devam edebilirsin.

---

## English

### Why you? (No expertise needed)

DimABSA's valence/arousal gold values come from **ordinary readers**, not linguists:
several people give an intuitive rating to the same sentence and the ratings are averaged
(that's why the data has values like `7.83` or `6.38`). What we want is exactly your
ordinary, honest human judgement. There is no "correct answer", only what a reasonable
reader feels. When unsure, trust your first impression and move on.

### What is labelled

Each record is one news headline with one or more **aspects**: the targets the headline
says something about.

| Field | Meaning | Example |
|---|---|---|
| **Aspect** | Target phrase copied *verbatim* from the headline; `NULL` if implicit | `Foreo Luna 5 LED`, `Black Friday deals` |
| **Opinion** | The evaluative phrase, verbatim; `NULL` if none | `best`, `misleading`, `20% off` |
| **Category** | `ENTITY#ATTRIBUTE`, see the list above | `PRODUCT#PRICES` |
| **Brand** | Which brand the aspect belongs to | `foreo`, `generic`, … |
| **Valence (V)** | negative ↔ positive, 1.00–9.00 | 1 very negative, 5 neutral/factual, 9 very positive |
| **Arousal (A)** | calm ↔ intense/excited, 1.00–9.00 | 1 calm/factual, 9 very intense |

Valence is *how good or bad* the headline is about the target. Arousal is *how intense*
it is, whatever the direction: a product recall is negative **and** fairly intense; "7 Best
Massage Guns" is positive but calm.

### Anchors (real examples from this set)

Valence: recall 2.25 · "misleading LED face masks" 2.25 · "one feature annoyed me" 3.25 ·
comparison question with no verdict 5.0 · first advent calendar launched 6.25 ·
"7 Best Massage Guns" / "20% off" 7.25 · "This New Launch Tops Them All" 8.25 ·
9 only for gushing, unlimited praise.

Arousal: factual corporate news 4.0 · informative best-of list 5–6 · deal excitement,
exclamation marks, "viral" 6–7 · "Sale is LIVE" 7.25 · "results are 'shocking'" 8.0 ·
9 only for extreme, shouty emotion.

Rule of thumb: the further V is from 5, the higher A tends to be (true in DimABSA too),
but a calm best-of list can be V 7, A 5.5.

### Brand values, Skip, workflow

Brand: a tracked id; `other` (named but untracked brand or retailer); `generic` (product
category, no brand); `unknown` (a specific product whose brand the headline hides).
`BrandInText = false` means the brand comes from the article, not the headline — check those.

Skip a headline with no beauty-tech target worth rating, or one you don't understand.
Low-confidence items come first (21). Accept when it looks right; move a slider and
**Save fix** when a value feels more than ~1 point off; don't fuss over 0.25–0.5.
Every click autosaves, so you can stop and resume any time.
