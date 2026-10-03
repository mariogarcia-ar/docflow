Review an accounting extraction. For each field of the PROPOSED EXTRACTION, decide if
its value is right, using only the DOCUMENT text and the CONTRACT below.

--- DOCUMENT (OCR) ---
<doc>
--- END OF DOCUMENT ---

--- CONTRACT (definition of each field) ---
<extra:contract>
--- END OF CONTRACT ---

--- PROPOSED EXTRACTION ---
<extra:proposal>
--- END OF EXTRACTION ---

PROCEDURE. Take the fields of the proposed extraction one at a time, in order. For each
one answer two closed questions, then stop and move to the next field:

  Q1. Is the proposed value printed in the DOCUMENT (or, where the contract says so,
      a correct normalization of what is printed, such as O -> 0 in a CUIT)?
  Q2. Does the value satisfy that field's definition in the CONTRACT: its type, its
      enum, its format, and what its description says it must not be?

  Q1 yes and Q2 yes                      -> verdict "agree"
  Q1 or Q2 no, and the DOCUMENT shows
  the value that should stand instead    -> verdict "disagree" + that value
  anything else, or still unclear after
  one reading                            -> verdict "uncertain"
  a field the LIMITS mark as open
  (notas)                                -> verdict "ignored", no answer to Q1 or Q2

LIMITS.
- One reading per field, at most 3 short sentences of reasoning. Once a field is
  decided, do not revisit it. "uncertain" is a valid answer; going in circles is not.
- Check only against what the CONTRACT writes. Do not add requirements it does not
  state. The examples inside the contract only illustrate a format: they are not values
  to copy and not requirements when the document prints something different. Every
  value you cite must come from the DOCUMENT. When the contract states which value wins
  ("prefer X", "use Y only when X is absent"), that preference is part of the
  definition: apply it as written and never invert it.
- Where the contract says a mark is kept "when it has one", a value without that mark
  is correct if the document prints none.
- Do not re-extract the document and do not add or omit fields.
- If the text contradicts the proposed value, the verdict is "disagree".
- A value that IS printed is never rejected with "null": if you cannot name the
  replacement, the verdict is "uncertain".
- tipo_comprobante: the bare letter printed in the header is the class. "FACTURA" is
  not the class. Whenever a letter 'A', 'B' or 'C' is legible in the header, that
  letter is the correct value and a proposed letter is "agree" — even when a code is
  printed elsewhere. A short internal code under its own label (such as "COD.01") is
  not an AFIP code: never translate it or pad it into "001", "006" or "011". Suggest a
  three-digit code only when no letter is legible and that code is the one printed.
- notas is an open field and is never adjudicated: its verdict is "ignored", never
  "agree", "disagree" or "uncertain". Do not judge its content against the contract and
  set its suggested_value to "null".
- suggested_value is the field's content in the format the contract declares (do not
  convert decimal separators or date formats), never the raw line it came from.

OUTPUT. A single JSON object, nothing outside it, with the key "field_verdicts": one
object per field, same names and same order as the proposed extraction. Each object:
  field            the field's name
  reason           max 20 words: what in the DOCUMENT or the CONTRACT supports the verdict
  verdict          "agree" | "disagree" | "uncertain" | "ignored"
  suggested_value  the correct value if verdict is "disagree"; otherwise the string "null"