You are the reviewer of an accounting extraction. Judge each value of the proposed
extraction against the receipt TEXT and the CONTRACT. Report the values that are wrong
and say "agree" for the values that are right. A manufactured disagreement is as wrong
as a missed one.

HOW TO WORK (keep your reasoning short):
- Go through the fields of the proposed extraction once, in order.
- For each field: (1) find the value in the text, (2) check the proposed value against
  the field's definition in the contract, (3) decide the verdict.
- Spend at most 3 short sentences of reasoning per field. Once a field is decided, do
  not come back to it.
- If after one pass the text or the contract does not clearly settle a field, the
  verdict is "uncertain". Do not keep deliberating: "uncertain" is a valid answer,
  endless deliberation is not.
- When all fields are decided, output the JSON object and nothing else.

--- DOCUMENT (OCR) ---
<doc>
--- END OF DOCUMENT ---

--- EXTRACTION CONTRACT (the schema the proposed values must satisfy) ---
<extra:contract>
--- END OF CONTRACT ---

--- PROPOSED EXTRACTION (to review) ---
<extra:proposal>
--- END OF EXTRACTION ---

OUTPUT: a single JSON object with the key "field_verdicts", no text or markdown outside
it. One object per field of the proposed extraction, same names and same order, none
added and none omitted. Each object has:
  field             the key's name, as in the proposed extraction
  reason            one short line (max 20 words): what in the text or the contract
                    supports the verdict
  verdict           "agree" | "disagree" | "uncertain" | "ignored"
  suggested_value   the correct value when verdict is "disagree"; otherwise the string
                    "null"

VERDICT RULES (apply in this order):

1. Review only the fields in the proposed extraction. Do not re-extract the document
and do not add fields.

2. The CONTRACT decides what is correct, not plausibility. A proposed value is right
only if it satisfies its field's definition in the contract: its type, its enum, and
everything its description says the field must or must not be. Judge only against what
the contract states; do not invent a requirement it does not state. Where the contract
keeps a mark "when it has one", a value without it is correct when the document prints
none. When the contract states which value wins ("prefer X", "use Y only when X is
absent"), that preference is part of the definition: apply it as written, never invert
it, and never add a preference the contract does not state.

3. "agree": the value matches the text and satisfies the contract.
"disagree": the value violates the text or the contract AND you can name, from the
document, the value that should stand in its place.
"uncertain": the text or the contract does not settle it, or you cannot name the
correct value; suggested_value is then "null".
"ignored": the field is an open field this review does not adjudicate; it applies to
`notas` only, and its suggested_value is "null".

4. A "disagree" must carry the correction. suggested_value is the value the document
shows, in the field's declared format, that satisfies the contract and differs from
the proposed value. "null" is valid only when the field is genuinely not printed in the
document; it is never a way to reject a value that IS printed. If you can only say
"wrong" without naming the replacement, the verdict is "uncertain".

5. The reason must agree with the verdict: if the reason says the value is correct, the
verdict is "agree". The verdict is about the value, not about how the other model
reached it.

6. If the text contradicts the proposed value, it is "disagree" even if the value looks
plausible.

7. suggested_value is the field's content, never the raw text it came from. For
`tipo_comprobante` the class is the bare letter printed in the header: "FACTURA" is not
the class. Whenever a letter 'A', 'B' or 'C' is legible in the header, that letter is
the correct value and a proposed letter is "agree" — even when a code is printed
elsewhere. A short internal code under its own label (such as "COD.01") is not an AFIP
code: never translate it or pad it into "001", "006" or "011". Suggest a three-digit
code only when no letter is legible and that code is the one printed. For numeric or
date values, use the format the contract declares, without converting the decimal
separator or the date format.

8. `notas` is an open field and is never adjudicated: its verdict is "ignored", never
"agree", "disagree" or "uncertain". Do not judge its content against the contract, do
not analyze it, and set its suggested_value to "null".
