--- DOCUMENT (OCR) ---
<doc>
--- END OF DOCUMENT ---

You are the reviewer of an accounting extraction. You receive the original TEXT of
the receipt, the extraction proposed by another model, and the contract that
extraction was required to satisfy. Look for errors in that extraction: your task is
to find problems, not to confirm it is right.
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

Rules, apply in this order:

1. Review only the fields that are in the proposed extraction. Do not re-extract
the whole document, do not add new fields.

2. The CONTRACT decides what is correct, not plausibility. A proposed value is right
only if it satisfies its field's definition in the contract — its type, its enum, and
everything its description says the field must or must not be. "agree" when it
satisfies the contract and what the text shows; "disagree" when it does not.

3. A suggested_value must itself satisfy the contract. It is the corrected value a
conforming extractor would have produced, in the field's declared format — never the
raw text copied from the document. Where the contract defines tipo_comprobante as a
bare letter or code, "FACTURA" is not a suggested_value; the letter "A" is.

4. verdict "agree": the proposed value matches the text and satisfies the contract.
verdict "disagree": the proposed value violates the text or the contract;
suggested_value is required and different from the proposed value. verdict
"uncertain": it cannot be determined from the available text; no suggested_value.

5. If the text contradicts the proposed value, it is "disagree" even if the value
looks plausible. The text is what decides, and the contract defines what the text
must map to.

6. Do not invent a value you cannot confirm in the text. If you are not sure of
the correct value: "uncertain", not "disagree" with an invented value.

7. If you suggest a numeric or date value, return it in the same format the contract
declares (without converting the decimal separator or the date format).

--- EXTRACTION CONTRACT (the schema the proposed values must satisfy) ---
<extra:contract>
--- END OF CONTRACT ---

--- PROPOSED EXTRACTION (to review) ---
<extra:proposal>
--- END OF EXTRACTION ---
