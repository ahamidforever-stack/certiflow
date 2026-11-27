"""Office house style: how the office lays out every certified translation.

Language-neutral. Sizes are deltas from the target profile's body size, so the
same house style works for a 13 pt Arabic body and a 12 pt English body.
Stored with the template asset (``house_style``); the defaults are neutral.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class HouseStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # sizes relative to the profile body size
    title_delta_pt: float = 2
    section_delta_pt: float = 1
    subheading_delta_pt: float = 0
    note_delta_pt: float = -2
    table_delta_pt: float = 0

    # paragraph spacing (pt)
    para_after_pt: float = 3
    title_after_pt: float = 3
    section_before_pt: float = 7
    section_after_pt: float = 3
    line_spacing: Optional[float] = None      # None = single (no explicit line rule)

    # colours
    section_fill: Optional[str] = "D9E2F3"     # heading level 2 shown as a shaded bar
    label_fill: Optional[str] = "F2F2F2"       # field labels in kv tables
    header_fill: Optional[str] = "F2F2F2"      # table header rows
    border_color: str = "808080"
    note_color: Optional[str] = "1F3864"
    note_italic: bool = True

    # tables
    cell_margin_lr_twips: int = 90
    cell_margin_tb_twips: int = 40
    label_after_pt: float = 1.5
    value_after_pt: float = 2
    value_align: Literal["start", "justify"] = "justify"
    spacer_after_table: bool = True
    spacer_size_pt: float = 14
    spacer_after_pt: float = 2

    # text
    body_align: Literal["start", "justify"] = "justify"
    note_wrap: str = "//{text}//"
    number_label: Literal["isolated_digits", "plain"] = "isolated_digits"   # ‎1‎.‏  in RTL
    number_gap: str = "  "
    bullet: str = "•  "
    bullet_indent_twips: int = 500
    latin_in_target_font: bool = True          # identifiers use the target font (e.g. Sakkal Majalla)


DEFAULT = HouseStyle()
