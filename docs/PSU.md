# PSU analysis

The FFDC analyzer includes a deterministic CFF PSU decoder based on the supplied
`psu-analysis` package:

- CFF Power Supply v4 specification Rev. 3.1
- CFF Power Supply v5 specification Rev. 2.4
- `spec和log对照表.docx`

Platform selection follows the supplied guide. SR650V3, SR630V3, SR665V3,
SR645V3, SR655V3 and SR635V3 use the v4 definitions. SR650V4 and SR630V4 use
v5. A `psu_dump.log` fixed-record source uses the v5 record layout, and an
unidentified source is marked as inferred instead of silently mixing layouts.

The parser discovers `psu_log_info` and `psu_dump.log` under the extracted FFDC.
It retains the raw D0h/D2h lines, reports the first four physical records per
PSU, decodes D0h date and counters, decodes D2h composite status bytes, and
converts VBULK using the documented little-endian rule. Current, temperature,
and fan values remain raw when the supplied guide does not define a universal
conversion. Electrical faults, warnings, and protocol flags are reported as
separate findings.

PSU records are point-in-time evidence. The analyzer does not infer current PSU
health or attribute a PSU event to a physical component without matching device
identity and timeline evidence.
