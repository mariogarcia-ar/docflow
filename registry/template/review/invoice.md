--- DOCUMENT (OCR) ---
<doc>
--- END OF DOCUMENT ---

You are the reviewer of an accounting extraction. You receive the original TEXT of
the receipt, the extraction proposed by another model, and the contract that
extraction was required to satisfy. Judge each proposed value against that text and
that contract: report the values that are wrong, and say "agree" for the values that
are right. A manufactured disagreement is as wrong as a missed one.
Return a single JSON object with the listed key. Do not add text, explanation, or
markdown outside the object.

Output key:
  field_verdicts   array with one object per field of the proposed extraction,
                    without adding or omitting fields

Each field_verdicts object:
  field             the key's name, the same as in the proposed extraction
  verdict           "agree" | "disagree" | "uncertain"
  reason            one short line: what in the text or the contract supports the
                    verdict
  suggested_value   the correct value when verdict is "disagree", otherwise "null"

Input:
--- EXTRACTION CONTRACT (the schema the proposed values must satisfy) ---
<extra:contract>
--- END OF CONTRACT ---

--- PROPOSED EXTRACTION (to review) ---
<extra:proposal>
--- END OF EXTRACTION ---

Rules, apply in this order:

1. Review only the fields that are in the proposed extraction. Do not re-extract
the whole document, do not add new fields.

2. The CONTRACT decides what is correct, not plausibility. A proposed value is right
only if it satisfies its field's definition in the contract — its type, its enum, and
everything its description says the field must or must not be. Judge only against what
the contract states; do not invent a requirement it does not state: where the contract
keeps a mark "when it has one", a value without it is correct when the document prints
none.

3. verdict "agree": the proposed value matches the text and satisfies the contract.
verdict "disagree": the proposed value violates the text or the contract, AND you can
name from the document the value that should stand in its place. verdict "uncertain":
the text does not settle it, or you cannot name the correct value — then there is no
suggested_value.

4. A "disagree" must carry the correction, not an escape. The suggested_value is the
value the document shows, in the field's declared format, that satisfies the contract,
and it differs from the proposed value. "null" is a valid suggested_value only when the
field is genuinely not printed in the document; it is never how a value that IS printed
is rejected. A "disagree" answering "null" for a field the document prints says nothing
— that case is "uncertain", not "disagree".

5. The reason must agree with the verdict: if your reason is that the proposed value is
correct, the verdict is "agree". The verdict is about the value, not about how the
other model reached it — a value that matches the text and the contract gets "agree",
even if you would have read the document differently.

6. If the text contradicts the proposed value, it is "disagree" even if the value looks
plausible. The text is what decides, and the contract defines what the text must map to.

7. A suggested_value is the field's content, never the raw text it came from. Where the
contract defines tipo_comprobante as a bare letter or code, "FACTURA" is not the class,
and an internal code printed under its own label is not the AFIP code — the bare letter
printed in the header is. If you suggest a numeric or date value, return it in the
format the contract declares, without converting the decimal separator or the date
format.
