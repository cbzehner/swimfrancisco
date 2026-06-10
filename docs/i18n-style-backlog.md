# i18n style backlog

Leftover suggestions from the 2026-06-09 native-reviewer pass (one reviewer
per locale, diffed against `i18n/ui/en.toml` + `i18n/spots/en.toml`). Every
*error* found in that pass was fixed and shipped; these are the style-level
improvements that were deliberately deferred. None block anything — pick
them up opportunistically or hand the relevant section to a native speaker.

## es

- `aquatic-park` mixes numeric conventions: "0,25 mi", "$12,67" (decimal
  comma against US dollar amounts). Consider "$12.67" for a US-resident
  audience; "12,67" risks misreading.
- `crissy-field` "nada con marea parada o entrante" — "marea parada" is
  nonstandard; "repunte de marea (estoa)" is the term, or plainer "cuando
  la marea está quieta o subiendo".
- `martin-luther-king-jr-pool` uses both "chapoteadero" and "piscina
  infantil" for the same wading pool — pick one.
- "amenidades" (24HF Potrero, City Sports) → "instalaciones";
  `presidio-ymca-letterman` "carrileros" → "nadadores de carril".
- `sections.spots.title = "Spots"` untranslated (section has
  `render = false`; verify it never surfaces before bothering).

## fi

- `plan_ahead` "Suunnittele eteenpäin" is an anglicism → "Suunnittele
  etukäteen".
- `footer_credit` "…, tekijä" dangles before the linked name → "tekijä:".
- `subtype_membership_indoor` "jäsenyyssisäallas" is a clunky triple
  compound → "jäsenten sisäallas".
- `upcoming_closures` "Tulevat sulut" is ambiguous → "Tulevat sulkuajat".
- `chip_day_pass` "PÄIVÄLIPPU" vs spots' "Päiväpassi" terminology drift.
- Reason strings keep "9am–1pm" style times; Finnish convention is
  "klo 9–13".
- spots: baker "paikallistuntemus" editorializes "conservative swim
  plans"; "Mahdollinen jäsen" → "Jäsenyyttä harkitseva"; "kaappeihin" →
  "pukukaappeihin"; "sekki" → "shekki"; "$12" vs "12 $" drift.

## fil

- Program chips are formal Tagalog ("LANGOY SA LANE", "LANGOY PARA SA
  NAKATATANDA" — 26 chars); everyday SF Taglish would be "LAP SWIM" /
  "SENIOR SWIM" and is much shorter. Switch if chips ever feel long.
- "tagapagligtas" is formal for lifeguard; Taglish "lifeguard" matches the
  register elsewhere.
- `crissy-field` description_short "malakas na tide" loses the
  height-vs-current distinction → "malakas na agos ng tide".
- `china-beach` "sa panahon ng season" is redundant → "seasonal lang ang
  lifeguard".
- `status_available = "PUWEDE"` is terse/vague alone; defensible as a pill.

## vi

- `access_hours_only` "CHỈ LÀ GIỜ VÀO CƠ SỞ" — "CHỈ LÀ" is weak spoken
  register → "CHỈ GIỜ MỞ CỬA CƠ SỞ".
- `lap = "BƠI LÀN"` vs `lap_swim = "BƠI THEO LÀN"` doublet — unify if not
  intentional.
- `upcoming_closures` "Sắp đóng cửa" reads as a status, not a list heading
  → "Các đợt đóng cửa sắp tới" (same for upcoming_access_changes).
- `footer_credit` → "Được làm tại San Francisco bởi".
- `horizon_clear_calendar` "DỌN LỊCH" isn't an idiom → "DẸP LỊCH SANG BÊN".
- spots: 24HF Ocean "lập kế hoạch bơi đang hoạt động" is a calque;
  bay-club "Người quan tâm hội viên" → "Khách muốn đăng ký hội viên";
  sfsu "hồ hoạt động" → "hồ vận động/giải trí".

## zh-Hant

- `status_closes`/`status_opens` compose prefix-first ("開放於 6:00am");
  natural order puts the time first — needs the same pattern treatment
  `open_count_*` got if it ever grates.
- spots line ~26: 促銷→優惠 was fixed; scan for other Mainland-leaning
  vocabulary if more copy gets added (reviewer flagged none else).

## Cross-locale

- The deck sentence in `templates/index.html` hardcodes sentence shape
  around the count spans ("Bay X, Ocean Y."); fine today, same
  pattern-key treatment available if a locale ever needs reordering.
