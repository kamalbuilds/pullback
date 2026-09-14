"""Reading the one fact NEEDS_EVIDENCE says it is missing.

`agent/engine/verdict.py` sometimes reaches a case where every checkable
constraint passed but there was not enough on the receipt to be sure, and it
names the single fact that would settle it: a UPC, a model number, a lot or
batch code. That fact is never in anyone's head. It is stamped or printed on
the object itself, usually somewhere unglamorous: the underside of a bottle,
a sewn-in seam label, a sticker on the back of a housing. A household member
can photograph it. This module reads the photograph.

The read is honest about three different situations, because they are not
the same failure:

    read          the characters are legible and reported as printed
    not_present   the label is legible and this kind of code simply is not
                  on it (a soft toy has no UPC on the plush itself, only on
                  the swing tag)
    unreadable    something about the photo (blur, distance, glare, crop,
                  darkness) makes the text untrustworthy, so nothing is
                  reported for it

Guessing a code that only looks plausible is worse than reporting nothing:
`_upc_check` and `_model_check` in verdict.py treat any identifier as
decisive in either direction, so a wrong guess does not just fail to help,
it produces a false MATCH or a false NO_MATCH and, downstream of that, a
real claim mailed to a real company about a product the household may not
even own.

Of the three identifiers verdict.py can act on, only two are wired into it:
`_upc_check` reads `purchase.upc` against `constraints.upcs`, and
`_model_check` reads `purchase.model` against `constraints.models`. There is
no `_lot_code_check`, because no CPSC notice in this feed publishes a
canonical list of affected lot or batch codes the way it publishes a UPC
list; the lot code appears only as prose inside the notice description, if
at all. A lot code read from a label is therefore captured onto the
purchase record as evidence (`lot_code`, plus the full structured reading)
but, honestly, it cannot by itself flip a verdict in this engine today. The
round trip that actually moves a case from NEEDS_EVIDENCE to MATCH or
NO_MATCH is driven by a UPC or a model number read off the label, because
those are the two identifiers `decide()` knows how to check.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import BaseModel, Field
from strands import Agent
from strands.models.anthropic import AnthropicModel

from agent.engine.verdict import Purchase, Verdict, decide
from agent.feeds.base import Recall

MODEL_ID = "claude-sonnet-4-5-20250929"

ReadStatus = Literal["read", "not_present", "unreadable"]

_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


class CodeField(BaseModel):
    """One kind of stamped code, and what the model actually saw."""

    status: ReadStatus = Field(
        description="'read' only if the characters are legible enough to type with "
        "confidence. 'not_present' if the label is legible but this code type is not "
        "on it. 'unreadable' if this code's location is visible but the text is too "
        "small, blurry, angled, dark, or obstructed to make out."
    )
    value: str | None = Field(
        default=None,
        description="The exact string as printed, including its own dashes, spaces "
        "and slashes. Only set when status is 'read'.",
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="0.0 unless status is 'read'."
    )
    region: str = Field(
        default="",
        description="Where on the label this is, or would be, in plain words: "
        "e.g. 'printed on the barcode sticker on the underside' or 'sewn into the "
        "inside seam label near the care instructions'.",
    )
    note: str = Field(
        default="",
        description="Only when status is 'unreadable': what is wrong with the photo "
        "for this specific code and what a reshoot would need, e.g. 'text is legible "
        "as a location but too small at this distance, move the camera closer'.",
    )


class LabelReading(BaseModel):
    """What one photograph of a product label actually shows."""

    image_legible: bool = Field(
        description="False only if the whole photograph is unusable for reading any "
        "text at all: extreme blur, near darkness, or the label entirely out of "
        "frame. A photo that is fine overall but has one small illegible code is "
        "still image_legible=true; only that one field is 'unreadable'."
    )
    reshoot_instruction: str = Field(
        default="",
        description="Set when image_legible is false: the concrete photo to take "
        "instead, e.g. 'move closer so the label fills the frame, in daylight'.",
    )
    manufacture_date: CodeField
    lot_code: CodeField
    model_number: CodeField
    upc: CodeField
    serial_number: CodeField
    other_codes: list[CodeField] = Field(
        default_factory=list,
        description="Any other stamped or printed code on the label that does not "
        "fit the named fields, e.g. a SKU, a certification number, a tracking code.",
    )
    summary: str = Field(
        description="One plain sentence: what was actually found, or why nothing was."
    )


SYSTEM_PROMPT = """You are reading one photograph of a physical product label, taken by a household member trying to find out whether the product they own has been recalled. What you read may be checked against a UPC or model number list and, if it matches, used to file a real claim with a real company. What you read may also clear the product of the recall. Both outcomes depend on you reporting only what is actually legible.

For every kind of code (manufacture date, lot or batch code, model number, UPC, serial number, and anything else stamped or printed that does not fit those names):

- Report status "read" only if you can see the actual characters clearly enough to type them with confidence. Transcribe exactly what is printed, including its own punctuation.
- Report status "not_present" if the label is legible overall but this kind of code genuinely is not printed anywhere on it.
- Report status "unreadable" if you can see roughly where this code would be but the text itself is too small, too blurry, too dark, cut off, or glare-obscured to actually read. Say what is wrong and what a reshoot needs.

Never invent or guess at a code that only looks plausible. If you are not sure you read every character correctly, that field is "unreadable", not "read". A wrong guess here becomes a false claim sent to a real manufacturer, or a false all-clear on a product that is actually dangerous.

A UPC-A barcode prints exactly 12 digits beneath its bars, grouped 1-5-5-1; EAN-13 prints 13, grouped 1-6-6. Count the digits you read against the bars themselves, one bar-group at a time, before reporting a UPC as "read". If the printed digits are small enough at this image's resolution that you cannot confidently place each digit against its bar, report "unreadable" and say the photo needs to be retaken closer to the barcode, not a best guess at the number. The grouping spaces under a barcode exist only to help a human eye, not part of the code itself: report the upc value as one contiguous run of digits with no spaces, even though you verified it group by group.

Set image_legible to false only when the whole photograph cannot be used to read any text: extreme blur, near darkness, or the label out of frame entirely. If the photo is fine but shows a beauty shot of the product with no label or text visible, that is image_legible=true and every code field is "not_present", because there is nothing wrong with the photo, there is simply no label in it."""


def _sniff_format(data: bytes) -> str:
    for magic, fmt in _MAGIC:
        if data.startswith(magic):
            return fmt
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise ValueError("Unrecognized image data: not a png, jpeg, gif or webp.")


def _load_image(source: str | Path | bytes) -> tuple[bytes, str]:
    if isinstance(source, bytes):
        data = source
    elif isinstance(source, (str, Path)):
        data = Path(source).read_bytes()
    else:
        raise TypeError(f"read_label expects a path or bytes, got {type(source)!r}")
    return data, _sniff_format(data)


def _pixel_size(data: bytes, fmt: str) -> tuple[int, int] | None:
    """Width, height read straight from the file header, no decode needed.

    Told to the model as text alongside the image because a resized or
    thumbnail-sized photo is exactly the case where it should downgrade a
    barcode to "unreadable" instead of guessing at digits too small to
    actually resolve.
    """
    if fmt == "png" and len(data) >= 24 and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if fmt == "jpeg":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height = int.from_bytes(data[i + 5 : i + 7], "big")
                width = int.from_bytes(data[i + 7 : i + 9], "big")
                return width, height
            i += 2 + seg_len
    return None


# CPSC's own product photos, the only real corpus available to test against,
# run 200-500px on a side: press-kit images, not the phone photo this feature
# is actually built for. At that size a barcode's individual digits are a
# handful of pixels wide and Claude will confidently misread them rather than
# say so. Interpolating up before sending does not add information the photo
# never had, but it measurably changes whether the model reports a UPC
# correctly instead of a wrong number at the same 0.9+ confidence: verified
# by hand against 26331's real UPC list, wrong below this, right above it.
_TARGET_LONG_EDGE = 1200
_MAX_UPSCALE = 6


def _upscale_if_small(data: bytes, fmt: str, size: tuple[int, int] | None) -> tuple[bytes, str]:
    if size is None:
        return data, fmt
    width, height = size
    long_edge = max(width, height)
    scale = min(_MAX_UPSCALE, _TARGET_LONG_EDGE / long_edge) if long_edge else 1.0
    if scale <= 1.0:
        return data, fmt
    with Image.open(BytesIO(data)) as im:
        resized = im.convert("RGB").resize(
            (round(width * scale), round(height * scale)), Image.LANCZOS
        )
        buf = BytesIO()
        resized.save(buf, format="PNG")
        return buf.getvalue(), "png"


def read_label(
    image_path_or_bytes: str | Path | bytes, *, asking_for: str, model_id: str = MODEL_ID
) -> LabelReading:
    """Read every stamped code visible in one product label photograph.

    `asking_for` is the plain-words fact `verdict.missing` names, e.g. "the
    UPC printed on the box". It is passed to the model as context for what
    the household is trying to answer, but every field is always read: a
    photo taken to answer one question often legibly answers another.
    """
    data, fmt = _load_image(image_path_or_bytes)
    size = _pixel_size(data, fmt)
    size_note = f"This photograph was captured at {size[0]}x{size[1]} pixels. " if size else ""
    data, fmt = _upscale_if_small(data, fmt, size)
    agent = Agent(
        model=AnthropicModel(model_id=model_id, max_tokens=2048),
        system_prompt=SYSTEM_PROMPT,
    )
    prompt = [
        {"image": {"format": fmt, "source": {"bytes": data}}},
        {
            "text": f"The household was asked for: {asking_for}\n\n"
            f"{size_note}Read this label photograph and report every code you can "
            "find on it, honestly, field by field."
        },
    ]
    result = agent(prompt, structured_output_model=LabelReading)
    if result.structured_output is None:
        raise RuntimeError("Model did not return a structured label reading.")
    return result.structured_output


_ENRICHABLE = {"upc": "upc", "model_number": "model", "lot_code": "lot_code"}


def apply_reading(purchase: dict, reading: LabelReading) -> dict:
    """Fold whatever was legibly read onto a copy of the purchase record.

    Only fields with status "read" are applied; "not_present" and
    "unreadable" leave the existing purchase value untouched rather than
    overwriting it with nothing. The full reading is attached as
    `label_reading` so a human auditing the case later can see exactly what
    the photo showed, not just the two or three values that made it into
    the purchase record.
    """
    enriched = dict(purchase)
    for field_name, purchase_key in _ENRICHABLE.items():
        field: CodeField = getattr(reading, field_name)
        if field.status != "read" or not field.value:
            continue
        value = field.value
        if field_name == "upc":
            # A barcode's grouping spaces are for a human eye, not part of the
            # code CPSC's own UPC list stores; strip them so the match in
            # verdict._upc_check compares digits to digits.
            value = "".join(value.split())
        enriched[purchase_key] = value
    enriched["label_reading"] = reading.model_dump(mode="json")
    return enriched


_PURCHASE_FIELDS = {
    "purchase_id",
    "description",
    "retailer",
    "purchased_on",
    "price",
    "upc",
    "model",
    "quantity",
}


def settle(purchase: dict, recall: Recall, reading: LabelReading) -> Verdict:
    """Re-run the verdict engine against a purchase enriched by a label read.

    `purchase` is the plain-dict shape the case store and the console use
    (see `agent/pullback_agent.py:households`), not the frozen `Purchase`
    dataclass verdict.py works in, so this builds the dataclass fresh from
    whatever the enrichment produced. No prompt reaches `decide`; the model
    already did its only job, reading, inside `read_label`.
    """
    enriched = apply_reading(purchase, reading)
    kwargs = {k: v for k, v in enriched.items() if k in _PURCHASE_FIELDS}
    purchased_on = kwargs.get("purchased_on")
    if isinstance(purchased_on, str):
        kwargs["purchased_on"] = date.fromisoformat(purchased_on)
    return decide(Purchase(**kwargs), recall)
