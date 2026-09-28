"""The original deck's visual language, extracted so added slides can match it.

Measured from proposal/PharmaColdOps_tune.pptx (the hand-designed first 12 pages)
by scripts/inspect_deck_style.py:

  fonts   Libre Baskerville (headings, 69 runs) · DM Sans / DM Sans Bold (body, 78)
  text    #454240 ink (119 runs) · #5C4E3D muted (19) · #FFFFFF on dark fills
  fills   #F7EDD4 cream cards · #DDD3BA sand · #FFFDFA paper · #B88E23 gold accent
          #063E5F deep blue panel · #454240 dark panel
  sizes   37pt page title · 18.5pt card heading · 14.5pt body · 11.5/10.5pt captions

Everything added to the deck uses these values, so nothing looks bolted on.
"""

FONT_TITLE = "Libre Baskerville"     # page and card headings
FONT_BODY = "DM Sans"                # body text
FONT_BODY_BOLD = "DM Sans Bold"      # bold runs (the deck uses a separate family)

INK = "454240"                       # primary text on cream
MUTED = "5C4E3D"                     # secondary text
GOLD = "B88E23"                      # accent: rules, numerals, bullets
DEEP_BLUE = "063E5F"                 # dark panel
DARK_PANEL = "454240"                # the risks panel on slide 12
CREAM = "F7EDD4"                     # card / highlight fill
SAND = "DDD3BA"                      # secondary fill
PAPER = "FFFDFA"                     # light panel
WHITE = "FFFFFF"

SIZE_TITLE = 37.0
SIZE_H1 = 24.0
SIZE_CARD_HEAD = 18.5
SIZE_BODY = 14.5
SIZE_SMALL = 11.5
SIZE_CAPTION = 10.5
