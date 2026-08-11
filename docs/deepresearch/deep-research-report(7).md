# Deep Research Report on a Real-Time Single-Lead ECG Monitoring Thesis System

## Executive summary and final recommendation

The proposed thesis topic is technically appropriate for an undergraduate electrical engineering project **if the scope is kept explicitly educational and non-diagnostic**. The most defensible architecture is a **single-lead acquisition chain** with **AD8232 analog conditioning**, **Arduino timing-controlled ADC sampling**, **USB/serial transport**, and **computer-side signal processing** that separates a **QRS-optimized detection branch** from a **morphology-preserving display/delineation branch**. That separation is important because the filtering that improves QRS detection is not always the filtering that best preserves P and T morphology for visual interpretation or interval estimation [1], [3], [11], [25]. citeturn9view0turn11view0turn14view0turn19view0

For the **main real-time R-peak detector**, the strongest practical recommendation is to use an **adaptive Pan–Tompkins family detector**, implemented either as a **Hamilton-style simplified derivative detector** or as **WFDB XQRS**, and to keep **classical Pan–Tompkins as the thesis baseline comparator**. Pan–Tompkins remains foundational and explainable; Hamilton-style detectors are efficient and well validated; XQRS adds a documented single-lead implementation with band-pass filtering, wavelet-based moving-wave integration, refractory logic, T-wave inspection, and backsearch, all in the official WFDB Python ecosystem [1]–[3], [11]. Recent benchmarking on single-lead telehealth ECGs also shows that detector choice matters much more under real-world noise than on clean benchmark data, which makes signal quality handling essential rather than optional [12]. citeturn9view0turn11view0turn14view0turn8view0

For **PQRST delineation**, the most realistic undergraduate design is **not** a full clinical-grade delineator. Instead, the system should perform **R-centered fiducial estimation**: estimate **Q and S** as local extrema around a corrected R location, estimate **T** in a post-QRS search window on a morphology-preserving filtered signal, and attempt **P-wave estimation only when signal quality is high and rhythm is relatively stable**. Full wavelet delineators such as the Martínez algorithm and PhysioNet ECGPUWAVE are highly valuable as **literature anchors and offline evaluation tools**, but they are more ambitious than necessary for the real-time part of this thesis [8]–[10], [15]. citeturn39search3turn39search0turn39search2turn39search5turn40search0

For **signal quality**, the project should combine **AD8232 lead-off status**, **flatline/clipping checks**, **baseline wander and mains-interference indicators**, **template-correlation or morphology-consistency SQI**, and **RR plausibility checks** into a simple confidence score. The literature is clear that low-quality single-lead ECG can substantially degrade QRS detection performance, and official AD8232 lead-off pins provide a hardware-level reliability cue that should directly gate the software analysis pipeline [12], [16], [17], [25]. citeturn20view0turn8view0turn35search2turn31view0

For the **arrhythmia module**, the best thesis decision is to keep it **rule-based**, transparent, and explicitly labeled as **preliminary educational warning logic rather than diagnosis**. A small machine-learning model can be discussed as optional future work or, at most, as a secondary exploratory experiment. The reasons are straightforward: rule-based logic is easier to justify from cited physiological thresholds, clearer to explain in a bachelor thesis, safer from overclaiming diagnosis, and far lighter in terms of data engineering and validation burden than even “lightweight” classifiers such as logistic regression, SVM, decision trees, or random forests [27]–[32]. citeturn16search3turn16search2turn42view1turn37search15turn16search12

The final implementation recommendation is therefore: **250 Hz Arduino acquisition**, **binary serial packets with sample index and lead-off bits**, **Python `pyserial + numpy + scipy + pyqtgraph + wfdb`**, a **display branch** around roughly **0.5–40 Hz**, a **QRS branch** around roughly **5–20/25 Hz**, **XQRS or Hamilton-style QRS detection**, **local-window PQRST estimation**, **multi-feature SQI gating**, and **rule-based warnings for bradycardia, tachycardia, irregular RR, premature beat suspicion, wide QRS, and poor signal**. Evaluation should combine **MIT-BIH Arrhythmia**, **QT Database**, **MIT-BIH Noise Stress Test**, **PWAVE**, **AFDB**, and optionally **LUDB** and **BUT QDB**, with separate reporting for **dataset-based performance** and **real AD8232 recordings** [11], [18]–[25]. citeturn14view0turn22view0turn22view1turn22view2turn41view0turn41view1turn22view3turn41view2

## Scope and safety boundary

This project should be framed, from the title page onward, as an **educational engineering system for signal acquisition, signal processing, fiducial estimation, and preliminary warning generation**, **not** as a medical diagnostic device. That distinction is not cosmetic. The AD8232 data sheet describes the device as an integrated ECG/biopotential signal-conditioning front end, but it also states that the example circuit is **not a complete system design** and that additional effort is required to ensure compliance with medical safety guidelines from regulatory agencies [25]. A review on handheld single-lead ECGs similarly emphasizes usefulness together with pitfalls, signal-quality concerns, and interpretation differences relative to standard 12-lead ECG [29]. citeturn20view1turn21view2turn42view1

Single-lead ECG is genuinely useful for rhythm-related tasks, heart rate estimation, and educational morphology analysis, but it is inherently limited for axis analysis, ischemia localization, multi-lead morphology comparison, and many conduction-pattern distinctions that rely on 12-lead context. The literature on handheld or single-lead ECG repeatedly discusses both usefulness and pitfalls, which means the thesis should avoid claims such as “arrhythmia diagnosis,” “clinical screening accuracy,” or “disease detection” unless there is a simultaneous gold-standard study that this project is not designed to perform [12], [29]. citeturn8view0turn42view1

A safe project boundary is therefore: the system may output **heart rate**, **R-peak times**, **estimated QRS width**, **estimated P/Q/S/T fiducials with confidence labels**, and **preliminary warning messages** such as “possible irregular rhythm” or “signal too poor for reliable analysis.” It should never output statements such as “AF diagnosed,” “PVC confirmed,” or “bundle branch block present.” Where clinical thresholds are borrowed for educational warning rules, the report should state that these thresholds are **context dependent**, are being used only as **engineering heuristics**, and do not substitute for clinical interpretation [27]–[29], [31]. citeturn16search3turn16search2turn42view1turn16search12

For human testing, the thesis should adopt conservative laboratory precautions: use only approved disposable electrodes, do not place electrodes over broken skin, stop any recording if discomfort occurs, and avoid subject connection to mains-powered experimental electronics unless proper isolation and institutional safety procedures are in place. The AD8232 documentation explicitly discusses current-limiting for the driven electrode path and recommends a resistor large enough to keep fault current below 10 µA; it also notes that the reference application is not a complete medical-safe design [25]. citeturn19view0turn21view0turn21view2

## ECG signal and low-cost single-lead constraints

The AD8232 is a **fully integrated single-lead ECG front end** with an instrumentation amplifier, an auxiliary op-amp for gain/filtering, a right-leg-drive amplifier, a midsupply reference buffer, lead-off detection circuitry, and automatic fast-restore behavior. It is explicitly intended to extract, amplify, and filter small biopotential signals under noisy conditions such as motion or remote electrode placement, and it is designed to make the signal easy for an ultralow-power ADC or embedded microcontroller to acquire [25]. citeturn20view2turn20view1

For this project, the most important “what the AD8232 does” points are these. It provides **analog front-end conditioning**, **reference biasing**, **lead-off status outputs**, and **good ADC drive capability**. It also supports **two- and three-electrode configurations**. In three-electrode mode it can support dc lead-off detection and identify which input lead is disconnected; in two-electrode mode it can perform ac lead-off detection, but only indicates that an electrode has lost contact, not which one [25]. citeturn20view0turn19view0

The most important “what the AD8232 does not do” points are equally important. It does **not** guarantee diagnostic quality, does **not** prevent all motion artifact, does **not** eliminate baseline drift or power-line contamination under all circumstances, and does **not** make the overall system medically compliant by itself. The data sheet explicitly warns that its example monitor circuit is not a complete medical-safe design [25]. citeturn21view2

On the microcontroller side, the standard Arduino Uno environment gives a **10-bit ADC**. Official Arduino documentation states that on an Uno this maps the input range to values from 0 to 1023, yielding a nominal step of approximately **4.9 mV per count when referenced to 5 V** [26]. That is acceptable for an educational prototype when the AD8232 output swing is scaled sensibly, but it is still a real limitation: if the analog reference is poorly chosen, much of the ADC range can be wasted and low-amplitude morphology becomes visibly quantized. Because the AD8232 output is referenced around its internal reference buffer and is meant to drive an ADC, **ADC reference selection and full-scale matching are part of the signal-processing design, not an afterthought** [25], [26]. citeturn20view1turn6search11turn6search5

Electrode placement and motion remain major constraints. The AD8232 is designed to tolerate noisy conditions, but the same data sheet notes tradeoffs in right-leg-drive stability, reference-node susceptibility, and motion-related noise in ambulatory use; it even presents an accelerometer-assisted monitor as a way to further minimize motion-related noise [25]. Independent single-lead ECG literature also emphasizes signal-quality improvement and interpretation pitfalls in practical use [29]. For the thesis, that means the evaluation chapter should include **rest**, **seated posture change**, **electrode reattachment**, **lead-off**, and **mild movement** scenarios rather than only clean bench traces [25], [29]. citeturn19view0turn21view2turn42view1

A final constraint is conceptual rather than hardware-related: **P and T waves are usually much less robust than QRS in low-cost single-lead recordings**. Wavelet and phasor-transform delineation papers repeatedly note that low-amplitude P and T morphology, noise, and baseline effects make those waves more difficult than QRS, especially in single-lead data [8]–[10], [15], [16]. That is why the thesis should describe PQRST output as **estimated fiducials with confidence**, not as guaranteed morphological truth [8]–[10]. citeturn39search3turn39search0turn40search0turn39search2

## Real-time QRS and R-peak detection algorithms

The literature on QRS detection is large, but for this project the right comparison is not “which method is globally state of the art.” The right comparison is “which method is accurate enough, causal enough, transparent enough, and robust enough for a **single-lead, noisy, low-cost educational system running on a PC in real time**.” In that setting, **adaptive threshold detectors with simple preprocessing remain highly competitive**, while complex wavelet or template methods are best used selectively when their robustness justifies the extra algorithmic burden [1]–[7], [12], [13]. citeturn9view0turn11view0turn27search0turn26view1turn38view0turn8view0turn28search0

**Pan–Tompkins** remains the canonical baseline. Its causal chain—band-pass filtering, derivative, squaring, moving-window integration, adaptive thresholds, refractory logic, and a T-wave discrimination rule—still anchors undergraduate ECG education because it is interpretable and because nearly every later threshold-based detector is, in some way, a refinement of the same logic [1], [4]. In the original paper’s MIT-BIH table, Pan and Tompkins reported 507 false positives and 277 false negatives over 116,137 beats; this corresponds to approximately **Se = 99.76%** and **PPV = 99.56%** if calculated directly from the published totals [1]. citeturn9view0

**Hamilton/Tompkins-style detectors** are often a better fit for modern implementations than raw Pan–Tompkins. Hamilton’s later open-source description states that the detector is based on the Pan–Tompkins family, uses a single channel, is efficient, and is easily adapted to different sample rates. It also describes a practical simplification: low-pass, high-pass, absolute derivative, 80 ms moving average, peak detection, and decision rules with refractory blanking, baseline-shift rejection, T-wave rejection, adaptive thresholds, and search-back [3]. Reported performance in that open-source work was around **99.74% sensitivity and 99.81% positive predictivity on MIT-BIH** for the original detector variant, with similarly high values for the simplified variant [3]. citeturn11view0

**Elgendi’s optimized knowledge-based detector** is a strong lightweight alternative. It was explicitly developed for battery-driven and continuous monitoring settings, uses simple preprocessing plus knowledge-based thresholding, and is frequently cited in later benchmarking work as a high-efficiency method [4], [5], [12]. In later multi-dataset comparisons cited by Kristof et al., the optimized knowledge-based family performed very well on high-quality signals, which is relevant because your project will often operate on short, relatively clean seated recordings during demonstrations even if it must also handle poorer quality conditions [12]. citeturn27search0turn25search12turn8view0

**Kim and Shin’s spatiotemporal detector** is another attractive undergraduate option because it is explicitly positioned as a simple real-time detector using amplitude and duration criteria without wavelet transforms. In their PLOS ONE paper they reported **Se = 99.90% and PPV = 99.91% on MIT-BIH**, and they also reported strong performance on the AHA database and resilience above **5 dB SNR** on a noisy MIT-BIH test record [6]. Its main practical benefit is that the signal path is conceptually simple enough for thesis exposition while still reflecting more modern robustness thinking than bare Pan–Tompkins [6]. citeturn26view1

**Christov’s combined adaptive-threshold detector** deserves attention as another real-time candidate. It combines differentiated ECG information with an adaptive threshold composed of a slew-rate term, a high-frequency-noise term, and an anti-missed-beat term. Christov reported **Se = 99.69%** for a current-beat detector and **Se = 99.74%** for the RR-assisted variant on all 48 MIT-BIH records, with matching specificity around **99.65%** [7]. This is strong evidence that carefully designed adaptive-threshold logic can remain competitive without heavy transforms [7]. citeturn38view0

**Wavelet-based QRS detectors** are academically important and can be very strong, especially when morphology varies and noise is nonstationary. Li, Zheng, and Tai’s seminal wavelet paper framed wavelet transforms as a way to detect ECG characteristic points while handling high P/T waves, noise, baseline drift, and QRS variability [8]. Wavelet methods are also central to later delineation systems [9], [10]. The tradeoff for your thesis is implementation complexity: even when transform complexity is nominally manageable, wavelet approaches usually bring additional scale selection, post-processing, and delineation rules that make them harder to defend as the main online detector for an undergraduate real-time build [6], [8]–[10]. citeturn39search3turn39search0turn40search0turn26view1

**Matched-filter methods** are classical and theoretically appealing because they maximize signal-to-noise ratio when template and noise assumptions are favorable. Thakor, Webster, and Tompkins’ “optimal QRS detector” is the classic representative [14]. In present practice, however, matched filters are often less attractive for a low-cost educational monitor because they can become template- or amplitude-dependent. This concern appears directly in WFDB’s documentation for **gqrs**, which states that the detector uses a QRS matched filter, depends strongly on configuration amplitude parameters, carries known issues inherited from the original C code, and is not being further developed or supported in the Python library [11]. That does not make matched filtering “bad”; it makes it a weaker mainline choice for a thesis whose priority is transparent robustness over algorithmic elegance [11], [14]. citeturn14view0turn13search0

A final practical point is that **detection accuracy and peak timing are not the same thing**. Official WFDB tooling provides both QRS detectors and a `correct_peaks` function specifically to shift detections onto local extrema, which is a clue that the raw output of many detectors is good enough for rate estimation but not always ideal for interval measurement [11]. For a thesis that later estimates Q, S, T, RR, and QRS width, **R-peak correction after primary detection is strongly recommended** [11]. citeturn14view0

**Table 1 — QRS/R-peak detection algorithm comparison**

| Algorithm | Core idea | Preprocessing needed | Latency | Complexity | Noise robustness | Real-time suitability | Fit for AD8232/Arduino data | Evidence strength | Recommendation |
|---|---|---|---|---|---|---|---|---|---|
| Pan–Tompkins [1], [4] | Band-pass + derivative + squaring + moving-window integration + adaptive thresholds | Moderate | Moderate, causal | Low | Moderate | Excellent | Good if paired with SQI and peak correction | Very high | **Use as the thesis baseline** |
| Hamilton / Hamilton-style [2], [3] | Pan–Tompkins family with practical rule refinements and simplified preprocessing | Moderate | Moderate, causal | Low | Good | Excellent | Very good | Very high | **Top practical choice** |
| WFDB XQRS [11] | 5–20 Hz band-pass + Ricker-wavelet MWI + adaptive thresholds + T-wave check + backsearch | Moderate | Moderate, causal | Low–moderate | Good | Excellent on PC | Very good | High | **Best implementation choice if WFDB is acceptable** |
| Elgendi optimized knowledge-based [4], [5] | Simple preprocessing with knowledge-based block and threshold logic | Low–moderate | Low–moderate | Low | Good on clean-to-moderate noise | Excellent | Good | High | **Strong alternative / comparison method** |
| Kim–Shin spatiotemporal [6] | Amplitude and duration criteria with simple FIR + moving averages | Low–moderate | Low–moderate | Low | Good; reported robust above 5 dB SNR | Excellent | Very good | High | **Strong comparison method** |
| Christov adaptive threshold [7] | Summed differentiated ECG and combined adaptive threshold | Moderate | Low–moderate | Low | Good | Excellent | Good | High | Useful optional comparison |
| Wavelet detector [8] | Multiscale transform emphasizes QRS singularities and morphology changes | Moderate–high | Moderate | Moderate | Good–very good | Good on PC | Good, but more coding burden | High | Better for literature and offline comparisons than main online detector |
| Matched filter / gqrs-like [11], [14] | Template-like QRS matched filtering plus threshold logic | Moderate | Low–moderate | Low–moderate | Variable; can be parameter sensitive | Good | Fair–good depending on tuning | Moderate | Not preferred as primary detector |

The qualitative labels in Table 1 synthesize the algorithm structures, validation papers, and official WFDB documentation in [1]–[7], [11], [12], [14]. The latency entries are **engineering inferences** from causal filter lengths, moving averages, and search-back behavior rather than measurements on your specific laptop. citeturn9view0turn11view0turn14view0turn26view1turn38view0turn8view0turn13search0

### Recommended detector decision

For the thesis itself, the strongest design is **two-tiered**. Implement **Pan–Tompkins** as the literature baseline because it is universally recognizable and easy to explain. Then implement **WFDB XQRS or a Hamilton-style detector as the system’s main detector**, because that gives better practical robustness, sample-rate flexibility, and straightforward benchmarking inside the Python/WFDB ecosystem [1]–[3], [11]. citeturn9view0turn11view0turn14view0

If the project team wants a third comparator, the best third option is **Kim–Shin or Elgendi**, not a heavy wavelet method. That gives a meaningful “noise-aware versus classical” comparison without exploding implementation complexity [5], [6]. citeturn27search0turn26view1

## PQRST delineation methods and signal quality indices

After R-peak detection, delineation methods fall into a few practically important families. The simplest are **fiducial-window methods**, where the algorithm searches within physiologically plausible time windows relative to each R peak; for example, searching left of R for Q, right of R for S, and later for T. These methods are attractive for undergraduate real-time systems because they are easy to implement, easy to debug, and easy to bound with simple confidence rules [8], [9], [15]. citeturn39search3turn39search0turn39search2

A second family is **local minima/maxima around R**, often on a morphology-preserving filtered signal. For single-lead low-cost data, this is especially suitable for **Q**, **S**, and often **T-peak** estimation. It becomes much less reliable for **P**, because P amplitude is smaller, morphology varies more, and the wave can be submerged by baseline shift, muscle artifact, or preceding T distortion [8]–[10], [15], [16]. citeturn39search3turn39search0turn40search0turn15search18

A third family is **derivative, slope, and curvature methods**, where onset and offset are inferred from changes in slope energy or by returning to isoelectric regions. Hamilton’s open-source ECG analysis description gives a good example: beat width can be estimated either from isoelectric regions or from slope behavior around the detection point [3]. These methods are useful for QRS-onset and QRS-end approximation, but they become fragile when the baseline is moving or the morphology is broadened by artifact [3]. citeturn11view0

The strongest research-grade delineators are **wavelet-based methods**. Li, Zheng, and Tai’s 1995 work used wavelets to detect characteristic points in the presence of variable morphology, baseline drift, and high P/T waves [8]. Martínez et al. later developed a robust **single-lead wavelet-based delineator** that detects QRS, then individual waves and boundaries, and finally P and T peak/onset/end locations [9]. PhysioNet’s **ECGPUWAVE** operationalizes this general idea in a tool that detects QRS and locates the beginning, peak, and end of P, QRS, and ST-T waveforms [15]. In other words, wavelet delineation is absolutely part of the literature you should review—but it is probably too ambitious to re-derive from scratch as the core online method in a bachelor project [8], [9], [15]. citeturn39search3turn39search0turn39search2turn39search5

A compelling low-complexity compromise is the **phasor transform delineator** of Martínez, Alcaraz, and Rieta. Its abstract specifically describes it as a **single-lead** delineator with **robustness, low computational cost, and mathematical simplicity**, and it was designed to manage low-amplitude P and T waves more precisely than naïve extrema searches [10]. This makes phasor-based delineation an excellent literature point and a plausible “advanced future work” option for your thesis. But unless a ready-made implementation is adopted, it is still more involved than a pragmatic R-centered window method [10]. citeturn40search0turn40search2

For this particular project, the most defensible statement is this: **Q and S estimation can be made reasonably reliable**, **T-peak estimation can be moderately reliable on good segments**, and **P-wave estimation is the least reliable component and must carry an uncertainty flag**. That conclusion is consistent with the structure of the classical delineation literature and with later work emphasizing that P waves are low-amplitude and difficult under noise and pathology [8]–[10], [15], [16]. citeturn39search3turn39search0turn40search0turn15search18turn15search5

**Table 2 — PQRST delineation method comparison**

| Method | Detects | Strengths | Weaknesses | Single-lead suitability | Complexity | Recommended use in this project |
|---|---|---|---|---|---|---|
| R-centered time-window / fiducial search [8], [15] | Q, S, T peak; optional P peak | Simple, causal, easy to explain | Window tuning needed; weak under noise or unusual morphology | Good | Low | **Primary online method** |
| Local minima/maxima around corrected R [8], [15] | Q, S, R refinement, often T peak | Very easy to implement | Poor for P; vulnerable to baseline drift | Good for Q/S/T, poor for P | Low | **Use for Q and S; optional T** |
| Derivative / slope / curvature [3] | QRS onset/end, width, some fiducials | Useful for width and boundaries | Sensitive to noise and moving baseline | Moderate | Low–moderate | **Use for QRS width estimation only** |
| Wavelet-based delineation [8], [9], [15] | P, QRS, T peaks and boundaries | Strong literature support; robust and comprehensive | More complex to implement and validate | Good | Moderate–high | **Use offline for evaluation / literature benchmark** |
| Phasor-transform delineation [10] | Single-lead fiducials including low-amplitude waves | Robust, mathematically elegant, low cost | Less standard in undergraduate implementation practice | Good | Moderate | Consider as advanced extension, not core requirement |
| Template-guided / morphology consistency search [16] | Beat-consistent fiducials | Can stabilize repeated morphologies | Degrades if ectopy/noise changes morphology | Moderate | Moderate | Best used as a confidence aid rather than main delineator |

Table 2 is a synthesis of the single-lead delineation literature and the official ECGPUWAVE description in [3], [8]–[10], [15], [16]. For your real-time system, the critical insight is that **full delineation software and online educational estimation are not the same engineering problem**. citeturn11view0turn39search3turn39search0turn40search0turn39search2turn35search2

### Practical delineation recommendation

For the runtime system, use a **corrected R peak** as the anchor. Estimate **Q** as the most negative or most opposite-polarity point shortly before the corrected R; estimate **S** similarly shortly after R; estimate **QRS end / J-point proxy** from a slope-return or low-slope criterion; search for **T peak** in a post-QRS window; and search for **P peak** only when `SQI` is high, no lead-off is present, and RR behavior is stable. If not, report **“P/T unavailable or unreliable”** rather than forcing a fiducial. That is a stronger thesis design than pretending to delineate every beat equally well [3], [8]–[10], [15], [16]. citeturn11view0turn39search3turn39search0turn40search0turn39search2turn35search2

### Signal quality index for single-lead ECG

ECG signal quality assessment is essential for this project because modern benchmarking shows that even strong QRS detectors degrade sharply on low-quality single-lead telehealth ECGs [12]. The literature also shows that there is **no universal gold standard SQI**, so a pragmatic multi-feature approach is appropriate [16], [17]. citeturn8view0turn31view0

The most practical SQI components for your system are:

1. **AD8232 lead-off flags.** These should have the highest priority because they are hardware-level evidence that the input is not trustworthy [25].  
2. **Flatline, clipping, or saturation checks.** These are easy engineering checks and should immediately invalidate analysis.  
3. **Template or morphology consistency.** Orphanidou’s SQI family is highly relevant here; later benchmarking summaries describe physiologic feasibility checks followed by a template-correlation threshold around **0.66** [16].  
4. **RR plausibility.** Orphanidou-style logic uses heart-rate and interval plausibility checks before template matching, including HR range and RR extremes [16].  
5. **Baseline-relative power and spectral indicators.** Zhao and Zhang’s single-lead SQI fusion work found that a combination of **qSQI, pSQI, kSQI, and basSQI** outperformed smaller or larger feature sets on their datasets [17].  
6. **Power-line contamination indicator.** This can be implemented as a narrowband spectral power ratio around 50 or 60 Hz.  
7. **Motion artifact indicator.** If no accelerometer is available, use signal-domain bursts or abrupt baseline disturbance; if an accelerometer is later added, BUT QDB shows how motion information can enrich quality assessment [24]. citeturn20view0turn21view2turn35search2turn31view0turn41view2

**Table 3 — Signal Quality Index options**

| SQI feature | Detects | Required signal/data | Ease of implementation | Reliability | Suggested thresholding strategy | Citation |
|---|---|---|---|---|---|---|
| AD8232 `LOD+` / `LOD-` | Lead-off / disconnected electrode | AD8232 digital status pins | Very easy | High for contact loss | Immediate hard fail; suppress analysis | [25] |
| Flatline / zero variance | Cable loss, dead channel, stuck ADC | Raw ADC stream | Very easy | High | Hard fail if variance below small floor for a sustained window | [25] |
| Saturation / clipping | Out-of-range analog chain, motion bursts | Raw ADC stream | Very easy | High | Hard fail if repeated samples near ADC rails | [25], [26] |
| Template correlation SQI | Morphology inconsistency / corrupted beats | Detected beats + beat windows | Easy–moderate | High on repeated morphologies | Use beat-template average; low confidence if mean correlation < about 0.66 | [16] |
| HR / RR plausibility | Implausible rhythm due to noise or missed beats | R-peaks | Easy | Moderate–high | Apply feasibility gating before morphology analysis; Orphanidou-type checks include HR range, max RR gap, RR ratio | [16] |
| qSQI | Detector disagreement / R-peak matching degree | Two detector outputs or two R estimators | Moderate | Moderate | Use as soft penalty rather than hard fail unless disagreement is severe | [17] |
| pSQI | Spectral concentration in QRS-related band | FFT or PSD | Moderate | Moderate | Soft penalty when expected QRS-band power concentration drops | [17] |
| kSQI | Noise / shape abnormality via kurtosis | Signal statistics | Easy | Moderate | Soft penalty with empirically tuned thresholds | [17] |
| basSQI | Baseline wander burden | PSD below ~1 Hz relative to total band | Moderate | Moderate | Penalize if low-frequency power is abnormally large; confidence rises as basSQI approaches 1 | [17] |
| Power-line ratio | Mains interference | PSD near 50 or 60 Hz | Easy | Moderate | Penalize when narrowband mains power exceeds tuned fraction of total | [13], [17] |
| Motion-aware SQI | Free-living artifact / quality drift | ECG alone or ECG + accelerometer | Moderate | Moderate–high | If accelerometer available, combine with ECG SQI; otherwise use abrupt baseline/slope excursions | [24], [25] |

Zhao and Zhang’s work is especially useful for this project because it studied **single-lead ECG** and found that combining **qSQI, pSQI, kSQI, and basSQI** was better than using any one of them alone on their datasets [17]. Orphanidou-style feasibility plus template matching is also highly practical for real-time gating [16]. citeturn31view0turn32view0turn35search2

### Recommended confidence score

A good thesis-ready confidence score is a **three-level or four-level** system rather than a falsely precise “AI confidence” number. One practical design is:

- **Unreliable**: lead-off, flatline, clipping, or multiple SQI hard fails.  
- **Poor**: no lead-off, but morphology inconsistency or large baseline/mains contamination.  
- **Usable for rate and QRS only**: QRS reliable, but P/T unreliable.  
- **Usable for rate, QRS, and tentative PQRST estimation**: high template consistency, acceptable spectral SQI, stable RR.  

This design is faithful to the literature because both telehealth benchmarking and dedicated SQI studies show that **good QRS detection does not imply good morphology quality for more delicate measurements** [12], [16], [17], [24]. citeturn8view0turn35search2turn31view0turn41view2

## Non-diagnostic arrhythmia warning rules

The warning module should be described and implemented as **preliminary educational logic**, not rhythm diagnosis. It should only run when signal quality is at least “usable for rate and QRS” and should be **suppressed by poor-signal or lead-off flags** [12], [16], [25]. citeturn8view0turn35search2turn20view0

### Bradycardia warning

The 2018 ACC/AHA/HRS Bradycardia Guideline notes that the NIH definition of bradycardia is **heart rate < 60 bpm in adults** other than well-trained athletes, while the guideline’s own definitions section uses **sinus rate < 50 bpm** in its terminology for sinus bradycardia in the sinus node dysfunction context [27]. For a **non-diagnostic educational warning**, the safest design is a two-level approach: show **informational low-rate status** below 60 bpm, but reserve the actual “preliminary bradycardia warning” for **sustained rate below 50 bpm** or for a user-configurable threshold chosen by the supervisor [27]. citeturn16search3turn16search10

### Tachycardia warning

A general clinical convention treats **tachycardia as a rate above 100 bpm**, and wide-complex tachycardia references use the same threshold [32]. For a simple educational system, a sustained rate above **100 bpm** can trigger a **preliminary tachycardia warning**, but the thesis should explicitly state that exercise, stress, posture, and anxiety can all raise rate without pathology. A more conservative implementation can require persistence over several seconds to reduce nuisance warnings [32]. citeturn16search6

### Irregular RR warning

Unlike bradycardia or wide QRS, there is **no single universally safe, clinically generalizable RR-irregularity cutoff** that should be presented as diagnostic from a low-cost single-lead system. Reviews of AF detection show that RR irregularity is useful, but the exact features and thresholds vary across methods [31]. Therefore, the best thesis choice is to define **irregular RR warning** as an **engineering heuristic**, for example: “issue a warning if several successive RR intervals deviate substantially from a rolling median while SQI remains high.” This should be labeled explicitly as a design recommendation rather than a clinical threshold [16], [31]. citeturn35search2turn16search12

### Premature beat suspicion

Hamilton’s open-source ECG analysis is helpful here. It classifies an interval as **NV** when it is **less than 75% of the most recent NN interval**, which is a practical and interpretable prematurity rule [3]. For your project, that can be translated into a **premature beat suspicion** flag when one beat arrives markedly earlier than expected and beat morphology or width also differs. It should remain a **suspicion**, not a PVC/PAC diagnosis, because single-lead morphology and noise can confound the distinction [3], [29]. citeturn11view0turn42view1

### Wide QRS warning

The AHA/ACCF/HRS ECG interpretation recommendations define incomplete right bundle branch block in adults as **QRS duration 110–120 ms**, and broader wide-complex tachycardia references define **wide QRS** as **>120 ms** [28], [32]. For a non-diagnostic thesis system, **120 ms** is the appropriate threshold for a **wide-QRS warning**, but only when QRS width is measured on beats with good SQI and only after R-peak correction. The report should state that single-lead width estimation is approximate and can be broadened by artifact [3], [28], [32]. citeturn16search2turn16search6turn11view0

### Poor signal and unreliable analysis warning

This warning should dominate every other one. If lead-off is active, template correlation is poor, baseline or mains contamination is high, or flatline/clipping is detected, the system should output **“poor signal / unreliable analysis”** and suppress all rhythm warnings except perhaps “reconnect electrodes.” This priority is strongly supported by both the AD8232 hardware features and modern telehealth QRS benchmarking [12], [16], [17], [25]. citeturn20view0turn8view0turn35search2turn31view0

### Recommended rule logic

A defensible warning engine for the thesis is therefore:

1. **Hardware/SQI gate**: if lead-off or signal unusable, show only poor-signal warning.  
2. **Rate rules**: compute smoothed heart rate from recent RR intervals; flag low or high sustained rate.  
3. **Rhythm regularity rule**: if RR irregularity exceeds a conservative heuristic under good SQI, issue irregular-RR warning.  
4. **Beat abnormality suspicion**: if beat is premature and morphology or width differs, issue premature-beat suspicion.  
5. **Width rule**: if median high-confidence QRS width exceeds 120 ms, issue wide-QRS warning.  

That design is clinically safer than trying to classify named arrhythmias from low-cost single-lead data [27]–[29], [31], [32]. citeturn16search3turn16search2turn42view1turn16search12turn16search6

## Evaluation datasets and protocol

A strong thesis evaluation should separate **algorithm validation on public annotated datasets** from **system validation on your own AD8232/Arduino recordings**. Public datasets are necessary for reproducibility and comparison with literature; real hardware recordings are necessary to demonstrate that the end-to-end build survives electrode issues, motion, serial transport, and waveform variability [11], [18]–[25]. citeturn14view0turn22view0turn22view1turn22view2turn41view0turn41view1turn41view2

The **MIT-BIH Arrhythmia Database** remains the standard first benchmark for QRS detection. It contains **48 half-hour**, **two-channel** ambulatory ECG excerpts from **47 subjects**, sampled at **360 Hz**, with about **110,000 beat annotations**, and the reference beat labels were produced by consensus after independent cardiologist review [18]. This is the correct main dataset for baseline QRS detection and heartbeat-level abnormality studies [18]. citeturn22view0

The **QT Database** is the key resource for wave delineation and interval measurement because it provides **105 fifteen-minute two-lead recordings** with manually marked **onset, peak, and end** for P, QRS, T, and sometimes U waves on selected beats. All records are at **250 Hz** [19]. This is the main dataset for evaluating PQRST fiducials and temporal delineation error [19]. citeturn22view1turn23view0

The **MIT-BIH Noise Stress Test Database** is indispensable because it provides noisy variants of clean MIT-BIH signals with typical ambulatory noise and explicitly notes that **electrode motion artifact** is especially troublesome because it can mimic ectopic beats and is not easily removed by simple filters [20]. That observation is directly relevant to AD8232/Arduino recordings [20]. citeturn22view2

The **MIT-BIH Arrhythmia Database P-Wave Annotations** resource adds expert P-wave labels for **12 MIT-BIH signals** and is therefore a very practical supplementary dataset for studying how often your P-wave estimator is reasonable at all [23]. The page itself warns that not all present P waves are guaranteed to be labeled or correct, which is exactly the kind of limitation the thesis should state explicitly [23]. citeturn41view0

The **MIT-BIH Atrial Fibrillation Database** is useful for non-diagnostic irregular-RR warning studies. It includes **25 long-term recordings**, mostly paroxysmal AF, with **23 waveform records** that are **10 hours long** at **250 Hz** and have rhythm annotations. The beat annotations include both automated `.qrs` and, for some records, corrected `.qrsc` files [22]. This is valuable for exploratory evaluation of irregular-rhythm warnings without claiming AF diagnosis [22]. citeturn41view1

The **Lobachevsky University ECG Database** is not ambulatory and not single-lead, but it is valuable for delineation because it provides **200 ten-second 12-lead ECG records** sampled at **500 Hz** with manually annotated boundaries and peaks of **P, QRS, and T** waves. For a single-lead thesis, LUDB can be used in a limited role—for example, evaluating a delineation method on **lead II only**—but its short duration and non-ambulatory nature must be acknowledged [21]. citeturn22view3

The **BUT QDB** is particularly relevant for signal-quality work because it contains **one-lead ECG plus 3-axis accelerometer data**, includes explicit quality labeling, and distinguishes between segments where all waveforms are measurable, segments where QRS remains visible but morphology is not fully reliable, and segments where QRS cannot be reliably detected [24]. That makes it a valuable SQI dataset even though it is not a classical arrhythmia database [24]. citeturn41view2

**Table 4 — Dataset comparison**

| Dataset | Official source | Sampling rate | Records | Leads | Annotation type | Best use | Limitations | Python/WFDB usage |
|---|---|---:|---:|---|---|---|---|---|
| MIT-BIH Arrhythmia Database [18] | PhysioNet | 360 Hz | 48 half-hour excerpts | 2 | Beat annotations, arrhythmia labels | Primary QRS evaluation, beat-level abnormality studies | Ambulatory but older data; two-lead recordings rather than true single-lead | `wfdb.rdsamp`, `wfdb.rdann` |
| QT Database [19] | PhysioNet | 250 Hz | 105 × 15 min | 2 | Onset, peak, end of P/QRS/T/U on selected beats | Fiducial and interval evaluation | Only selected beats annotated; relatively low-artifact excerpts | `wfdb.rdsamp`, `wfdb.rdann` |
| MIT-BIH Noise Stress Test [20] | PhysioNet | Derived from MIT-BIH | 12 ECG + 3 noise records | 2 | Beat annotations inherited from source ECGs | Noise robustness, SQI stress testing | Built from synthetic mixing around selected source records | `wfdb.rdsamp`, `wfdb.rdann` |
| MIT-BIH P-Wave Annotations [23] | PhysioNet | Inherited from MIT-BIH (360 Hz) | 12 signals | 2 | Expert P-wave annotations | P-wave feasibility study | Page warns labels may not be exhaustive or fully perfect | `wfdb.rdann` |
| MIT-BIH Atrial Fibrillation Database [22] | PhysioNet | 250 Hz | 25 long-term recordings | 2 | Rhythm annotations; automated and some corrected beat files | Irregular-RR warning studies | Designed for AF research; not a general delineation database | `wfdb.rdsamp`, `wfdb.rdann` |
| LUDB [21] | PhysioNet | 500 Hz | 200 × 10 s | 12 | Manual boundaries and peaks of P/QRS/T | Supplementary delineation evaluation | Short, non-ambulatory, not single-lead | `wfdb.rdsamp`, `wfdb.rdann` |
| BUT QDB [24] | PhysioNet | 1000 Hz ECG, 100 Hz ACC | 18 long-term recordings | 1 ECG + ACC | Quality classes and consensus labels | SQI validation, motion-aware quality experiments | Not a beat-by-beat arrhythmia dataset | WFDB files + CSV annotations |

The dataset properties in Table 4 come from the official PhysioNet dataset pages, not from secondary summaries [18]–[24]. In the thesis, this table should be cited early in the evaluation chapter, because it clarifies why no single dataset can answer every question at once. citeturn22view0turn22view1turn22view2turn41view0turn41view1turn22view3turn41view2

### Evaluation metrics and protocol

Official PhysioNet/WFDB tooling defines QRS detector evaluation in terms of matched and unmatched annotations. The WFDB comparison code explicitly defines **TP**, **FP**, and **FN**, computes **Sensitivity = TP / Nref**, and **Positive Predictivity = TP / Ntest**, and provides a Python interface for benchmarking against MIT-BIH [11]. PhysioNet’s ECG evaluation guide also explains the broader evaluation framework and related tools [11]. citeturn30view0turn18search1turn18search8

**Table 5 — Evaluation metrics**

| Metric | Formula or definition | Used for | Interpretation | Required annotation | Notes |
|---|---|---|---|---|---|
| Sensitivity (Se) | TP / (TP + FN) | QRS detection, warning recall | Fraction of true events found | Reference event times | Officially supported in WFDB comparison [11] |
| Positive Predictive Value (PPV) | TP / (TP + FP) | QRS detection, warning precision | Fraction of predicted events that are correct | Reference event times | Officially supported in WFDB comparison [11] |
| F1-score | 2·Se·PPV / (Se + PPV) | Overall detection balance | Harmonic mean of recall and precision | Reference event times | Useful when comparing missed beats vs false alarms |
| Timing error | Difference between matched detected and reference fiducial times | R-peak and PQRST timing | Temporal precision | Reference fiducial times | Report mean, median, std, and absolute error |
| Processing latency | Time from sample arrival to displayed/flagged event | Real-time behavior | Lower is better | No external annotation required | Measure online in the software pipeline |
| Update rate | GUI refreshes or processed windows per second | Visualization performance | Stability of display | No | Record median and worst-case values |
| Dropped-sample rate | Missing sample count / expected sample count | Serial acquisition integrity | Lower is better | Sample counter or expected clock | Add packet counters in acquisition format |
| Packet loss rate | Corrupted or missing packets / sent packets | Serial transport integrity | Lower is better | Packet indices / checksum | Important for Arduino-to-PC validation |
| SQI classification accuracy | Agreement with labeled quality or known artifact state | SQI module | Higher is better | Quality labels or controlled artifact conditions | Use BUT QDB or labeled in-house recordings |
| Warning precision | TP / predicted warnings | Educational warning module | Lower false alarm burden | Warning reference labels | Keep non-diagnostic wording |
| False alarm rate | False warnings per minute or per record | Warning usability | Lower is better | Warning reference labels | Very important for user trust |

A key methodological point is tolerance. WFDB’s benchmark example uses a matching window of **0.1 × fs**, which is about **100 ms at 1000 Hz-scaled logic or 36 ms at 360 Hz** depending on implementation examples, and PhysioNet’s broader evaluation materials reflect standard tolerance-based matching [11]. For your thesis, that is acceptable for **primary QRS detection**, but you should **also** report **timing error** after peak correction because PQRST and QRS-width work are much more sensitive to temporal jitter than simple beat counting [11]. citeturn30view0

### Recommended protocol

The evaluation chapter should contain four layers:

**Dataset-based QRS evaluation.** Run Pan–Tompkins baseline and the chosen main detector on all 48 MIT-BIH records. Report Se, PPV, F1, and timing error after peak correction [11], [18]. citeturn30view0turn22view0

**Noise robustness evaluation.** Repeat on NSTDB mixtures or noisy records, and show how performance varies with clean vs contaminated conditions. The database specifically highlights electrode motion artifact as the hardest practical noise source, so separate that case in the results [20]. citeturn22view2

**Delineation evaluation.** On QTDB, compare estimated P/Q/S/T points and QRS onset/end against annotated fiducials; optionally use LUDB lead II and PWAVE as supplementary studies. Because P labels are sparse and uncertain, report P-wave performance separately and conservatively [19], [21], [23]. citeturn22view1turn23view0turn22view3turn41view0

**Real-system evaluation.** Record your own AD8232/Arduino signals in controlled scenarios: quiet rest, mild motion, lead-off, electrode reattachment, and, if allowed, posture change. Measure end-to-end latency, sample continuity, missed packets, SQI behavior, and warning suppression under poor signal. If no clinical reference ECG is available, keep claims qualitative and engineering-focused for this subsection [25], [29]. citeturn20view0turn21view2turn42view1

## Final implementation architecture, rule-based versus lightweight ML, thesis notes, weak sources, and references

### Final recommended system architecture

The final recommended architecture is:

**Acquisition.** Use the AD8232 in a three-electrode configuration when possible so that dc lead-off status can identify which lead is disconnected. Sample with a timer-controlled Arduino routine at **250 Hz**. That rate is a practical compromise: it matches major delineation and AF datasets such as QTDB and AFDB, is more than adequate for heart-rate and QRS work, and keeps serial and GUI load low. If the implementation is stable at 300–360 Hz, that is beneficial for timing resolution, but 250 Hz is the safer thesis recommendation [19], [22], [25], [26]. citeturn22view1turn41view1turn20view0turn6search11

**Serial packet format.** Prefer a **compact binary packet**, not line-based CSV, for the final implementation chapter. A practical packet is: sync byte, sample counter, ADC sample, status bits for `LOD+`/`LOD-`, and checksum. This makes packet-loss measurement trivial and reduces timing variability. If the student initially develops using CSV for simplicity, the thesis should still state that binary framing is the more robust engineering choice.

**Python stack.** Use `pyserial` for acquisition, `numpy` for arrays, `scipy.signal` for filtering, `pyqtgraph` for real-time visualization, and `wfdb` for dataset I/O, detector benchmarking, and annotation comparison. The official WFDB Python documentation directly supports QRS detection, peak correction, and annotation comparison [11]. citeturn14view0turn30view0

**Filtering.** Maintain **two signal branches**. The **display/morphology branch** should preserve low-frequency content better, suitable for human viewing and approximate P/T estimation. The **QRS branch** should emphasize QRS energy with a narrower band similar to Pan–Tompkins or XQRS logic. Do not use the same aggressively QRS-focused branch for all morphology work [1], [3], [11], [25]. citeturn9view0turn11view0turn14view0turn19view0

**QRS detector choice.** Use **XQRS or a Hamilton-style detector as the production detector**, with **Pan–Tompkins as the baseline comparator**. Correct the detected locations to local maxima before computing RR or measurement features [1]–[3], [11]. citeturn9view0turn11view0turn14view0

**PQRST delineation.** Use a **low-complexity online method**: corrected R, then local-window Q/S extrema, slope-based QRS end, T search in a post-QRS window, and P search only if SQI is high. For the evaluation chapter, compare your online estimates to **ECGPUWAVE** or the QTDB/LUDB annotations offline rather than claiming that your online heuristic is equivalent to a full delineator [9], [15], [19], [21]. citeturn39search0turn39search2turn22view1turn22view3

**Feature extraction.** Extract only thesis-relevant features: RR interval, smoothed heart rate, beat prematurity relative to rolling median, rough QRS width, T-peak timing if reliable, and confidence flags from SQI. Resist the temptation to compute a large clinical feature set that the system cannot validate.

**SQI module.** Use hierarchical gating: lead-off and hard-fail checks first; then morphology consistency and spectral quality; then confidence labeling for PQRST. This directly addresses the single-lead low-quality failure modes highlighted in telehealth and SQI literature [12], [16], [17], [24], [25]. citeturn8view0turn35search2turn31view0turn41view2turn20view0

**Warning module.** Keep it rule-based and non-diagnostic. Output warnings such as “preliminary low rate,” “preliminary high rate,” “possible irregular RR,” “possible premature beat,” “possible wide QRS,” and “poor signal / unreliable analysis.” Suppress rhythm warnings under poor SQI [27]–[29], [31], [32]. citeturn16search3turn16search2turn42view1turn16search12turn16search6

**Evaluation pipeline.** Use `wfdb.rdsamp` and `wfdb.rdann` for datasets; benchmark QRS detectors with `wfdb.processing.compare_annotations`; evaluate delineation on QTDB and supplementary resources; evaluate SQI using BUT QDB and NSTDB; evaluate real-system metrics on in-house recordings [11], [18]–[24]. citeturn14view0turn30view0turn22view0turn22view1turn22view2turn41view0turn41view1turn41view2

### Rule-based versus lightweight ML decision

For this thesis, **rule-based is the best primary choice**. The reasons are not ideological; they are methodological.

A **rule-based module** needs no training dataset, is easy to tie to cited physiological or engineering thresholds, is straightforward to debug, and is easy to defend in viva or thesis review. It is also less likely to overstate medical capability because every warning can be traced to a transparent condition such as sustained heart rate, RR irregularity, or QRS width. That is especially important in a single-lead, low-cost system where ambiguity is unavoidable [27]–[29], [31]. citeturn16search3turn16search2turn42view1turn16search12

A **lightweight ML model** such as logistic regression, SVM, decision tree, or random forest is feasible on a laptop, but its real burden is not compute. Its burden is **data curation, labeling, patient-wise splitting, class imbalance handling, feature scaling, calibration, and significantly broader evaluation**. Systematic reviews of ECG-arrhythmia ML note persistent issues around dataset dependence, reporting quality, and limited clinical translation even in much larger studies than a bachelor project can support [30]. citeturn37search15

For that reason, the strongest thesis recommendation is:

- Keep the **primary arrhythmia-risk module rule-based**.
- If time permits, add a **small optional ML appendix** that predicts only a coarse label such as **“normal-like / warning-like”** from hand-crafted features, using a clearly partitioned public dataset.
- Do **not** position the ML model as better diagnosis. Position it only as exploratory comparison.

That recommendation keeps the project rigorous without creating an evaluation burden that overwhelms undergraduate scope [29], [30]. citeturn42view1turn37search15

### Thesis integration notes

For the **literature review chapter**, the most defensible structure is: single-lead ECG constraints; classical and modern QRS detectors; delineation methods; signal-quality assessment; educational warning logic; and evaluation datasets. The literature review should explicitly distinguish **established facts** from **this thesis’s design decisions**.

For the **proposed method chapter**, clearly justify the split architecture: hardware acquisition, morphology branch, QRS branch, R-peak correction, local-window delineation, SQI gate, and rule-based warning module. A block diagram should show that poor signal can veto downstream analysis.

For the **implementation chapter**, focus on sampling timing, packet framing, thread or buffer architecture, filter design parameters, R-peak detector flow, fiducial-point estimator windows, SQI computation, and warning logic.

For the **evaluation chapter**, separate offline dataset benchmarks from live hardware tests. Show not only performance on clean public databases, but also what happens during noise, lead-off, and motion. That is where the educational value of the system is highest.

### Weak or excluded sources

The following source types were intentionally excluded from the evidentiary core of this report: hobby blogs, hookup tutorials as primary evidence, unsourced “ECG basics” web pages, random commercial marketing pages, and preprints or code repositories without a supporting peer-reviewed paper. Some such materials were useful for discovery but **not** for final claims.

Examples of materials that were **not used as primary evidence** include hobby tutorials around the AD8232, community blogs about Arduino ECG builds, Wikipedia summaries, Kaggle mirrors of PhysioNet data, and ResearchGate-only full-text copies when a publisher page, PubMed entry, or official PhysioNet page was available. A few blocked or inaccessible pages were also not relied on for final quantitative claims unless the same metadata or claim was independently supported by an official or peer-reviewed source.

## Complete IEEE-style references

[1] J. Pan and W. J. Tompkins, “A Real-Time QRS Detection Algorithm,” *IEEE Transactions on Biomedical Engineering*, vol. BME-32, no. 3, pp. 230–236, 1985.

[2] P. S. Hamilton and W. J. Tompkins, “Quantitative Investigation of QRS Detection Rules Using the MIT-BIH Arrhythmia Database,” *IEEE Transactions on Biomedical Engineering*, vol. 33, no. 12, pp. 1157–1165, 1986, doi: 10.1109/TBME.1986.325695.

[3] P. Hamilton, “Open Source ECG Analysis,” in *Computers in Cardiology*, 2002, pp. 101–104.

[4] M. Elgendi, B. Eskofier, S. Dokos, and D. Abbott, “Revisiting QRS Detection Methodologies for Portable, Wearable, Battery-Operated, and Wireless ECG Systems,” *PLOS ONE*, vol. 9, no. 1, e84018, 2014, doi: 10.1371/journal.pone.0084018. PMID: 24409290.

[5] M. Elgendi, “Fast QRS Detection with an Optimized Knowledge-Based Method: Evaluation on 11 Standard ECG Databases,” *PLOS ONE*, vol. 8, no. 9, e73557, 2013, doi: 10.1371/journal.pone.0073557. PMID: 24066054.

[6] J. Kim and H. Shin, “Simple and Robust Realtime QRS Detection Algorithm Based on Spatiotemporal Characteristic of the QRS Complex,” *PLOS ONE*, vol. 11, no. 3, e0150144, 2016, doi: 10.1371/journal.pone.0150144.

[7] I. I. Christov, “Real Time Electrocardiogram QRS Detection Using Combined Adaptive Threshold,” *BioMedical Engineering OnLine*, vol. 3, art. 28, 2004, doi: 10.1186/1475-925X-3-28.

[8] C. Li, C. Zheng, and C. Tai, “Detection of ECG Characteristic Points Using Wavelet Transforms,” *IEEE Transactions on Biomedical Engineering*, vol. 42, no. 1, pp. 21–28, 1995, doi: 10.1109/10.362922. PMID: 7851927.

[9] J. P. Martínez, R. Almeida, S. Olmos, A. P. Rocha, and P. Laguna, “A Wavelet-Based ECG Delineator: Evaluation on Standard Databases,” *IEEE Transactions on Biomedical Engineering*, vol. 51, no. 4, pp. 570–581, 2004, PMID: 15072211.

[10] A. Martínez, R. Alcaraz, and J. J. Rieta, “Application of the Phasor Transform for Automatic Delineation of Single-Lead ECG Fiducial Points,” *Physiological Measurement*, vol. 31, no. 11, pp. 1467–1485, 2010, PMID: 20871135.

[11] WFDB Python documentation, “`processing` — QRS detectors, peak correction, and evaluation,” MIT Laboratory for Computational Physiology, PhysioNet. Available: official WFDB Python documentation and source file on PhysioNet.

[12] F. Kristof *et al*., “QRS Detection in Single-Lead, Telehealth Electrocardiogram Signals: Benchmarking Open-Source Algorithms,” *PLOS Digital Health*, vol. 3, no. 8, e0000538, 2024, doi: 10.1371/journal.pdig.0000538.

[13] G. M. Friesen, T. C. Jannett, M. A. Jadallah, S. L. Yates, S. R. Quint, and H. T. Nagle, “A Comparison of the Noise Sensitivity of Nine QRS Detection Algorithms,” *IEEE Transactions on Biomedical Engineering*, vol. 37, no. 1, pp. 85–98, 1990, doi: 10.1109/10.43620. PMID: 2303275.

[14] N. V. Thakor, J. G. Webster, and W. J. Tompkins, “Optimal QRS Detector,” *Medical & Biological Engineering & Computing*, vol. 21, no. 3, pp. 343–350, 1983, doi: 10.1007/BF02478504. PMID: 6876910.

[15] PhysioNet, “ECGPUWAVE v1.3.4,” official WFDB/PhysioNet software documentation. Available: official PhysioNet ECGPUWAVE documentation page.

[16] C. Orphanidou, T. Bonnici, P. Charlton, D. Clifton, D. Vallance, and L. Tarassenko, “Signal-Quality Indices for the Electrocardiogram and Photoplethysmogram: Derivation and Applications to Wireless Monitoring,” *IEEE Journal of Biomedical and Health Informatics*, vol. 19, no. 3, pp. 832–838, 2015, PMID: 25069129.

[17] Z. Zhao and Y. Zhang, “SQI Quality Evaluation Mechanism of Single-Lead ECG Signal Based on Simple Heuristic Fusion and Fuzzy Comprehensive Evaluation,” *Frontiers in Physiology*, vol. 9, art. 727, 2018, doi: 10.3389/fphys.2018.00727.

[18] PhysioNet, “MIT-BIH Arrhythmia Database v1.0.0,” official dataset page, doi: 10.13026/C2F305.

[19] PhysioNet, “QT Database v1.0.0,” official dataset page. Available: official PhysioNet QT Database page and accompanying documentation.

[20] PhysioNet, “MIT-BIH Noise Stress Test Database v1.0.0,” official dataset page. Available: official PhysioNet NSTDB page.

[21] A. Kalyakulina *et al*., “Lobachevsky University Electrocardiography Database,” *PhysioNet*, version 1.0.1, 2021, doi: 10.13026/eegm-h675.

[22] PhysioNet, “MIT-BIH Atrial Fibrillation Database v1.0.0,” official dataset page. Available: official PhysioNet AFDB page.

[23] A. Nemcova, R. Smisek, M. Vitek, and L. Smital, “MIT-BIH Arrhythmia Database P-Wave Annotations,” *PhysioNet*, version 1.0.0, 2018, doi: 10.13026/C2108F.

[24] PhysioNet, “Brno University of Technology ECG Quality Database (BUT QDB) v1.0.0,” official dataset page. See also L. Smital *et al*., “Real-Time Quality Assessment of Long-Term ECG Signals Recorded by Wearables in Free-Living Conditions,” *IEEE Transactions on Biomedical Engineering*, 2020, doi: 10.1109/TBME.2020.2969719.

[25] Analog Devices, “AD8232: Heart Rate Monitor Front End, Rev. D,” official data sheet, 2020.

[26] Arduino, “`analogRead()`,” official Arduino Language Reference; see also official Arduino Uno hardware documentation and schematic.

[27] F. M. Kusumoto *et al*., “2018 ACC/AHA/HRS Guideline on the Evaluation and Management of Patients With Bradycardia and Cardiac Conduction Delay,” *Circulation*, 2019, doi: 10.1161/CIR.0000000000000628.

[28] B. Surawicz *et al*., “AHA/ACCF/HRS Recommendations for the Standardization and Interpretation of the Electrocardiogram, Part III,” *Circulation*, 2009, doi: 10.1161/CIRCULATIONAHA.108.191095.

[29] M. P. Witvliet, E. P. M. Karregat, J. C. L. Himmelreich, J. S. S. G. de Jong, W. A. M. Lucassen, and R. E. Harskamp, “Usefulness, Pitfalls and Interpretation of Handheld Single-Lead Electrocardiograms,” *Journal of Electrocardiology*, vol. 66, pp. 33–37, 2021, doi: 10.1016/j.jelectrocard.2021.02.011. PMID: 33725506.

[30] Q. Xiao, H. Hu, and coauthors, “Deep Learning-Based ECG Arrhythmia Classification: A Systematic Review,” *Applied Sciences*, vol. 13, no. 8, art. 4964, 2023, doi: 10.3390/app13084964.

[31] O. Faust, Y. Hagiwara, T. J. Hong, P. A. Valentina L. K. Samuel, and U. R. Acharya, “A Review of Atrial Fibrillation Detection Methods as a Service,” *International Journal of Environmental Research and Public Health*, 2020, PMCID: PMC7246533.

[32] M. A. Obando and coauthors, “Wide QRS Complex Tachycardia,” *StatPearls*, Treasure Island, FL, USA: StatPearls Publishing, 2023. Available through NCBI Bookshelf.