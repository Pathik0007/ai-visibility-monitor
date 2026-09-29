"""
Built-in list of business categories for the Category field's suggestions.

Covers Google's own business place types (the categories Google Business
Profile listings are filed under) plus common local-business wording people
actually type ("fish and chips shop", "mobile mechanic"). Kept as plain
lowercase noun phrases so they read naturally inside the generated
questions ("best seafood restaurant in North Ryde?").
"""

from __future__ import annotations

CATEGORIES: list[str] = sorted(set("""
accounting firm
acupuncturist
aged care facility
air conditioning contractor
airport shuttle service
alterations tailor
animal hospital
antique store
apartment complex
appliance repair service
appliance store
aquarium
architect
art gallery
art school
arts and crafts store
asian restaurant
auto body shop
auto electrician
auto parts store
bakery
bank
bar
barbecue restaurant
barber shop
bathroom renovator
beauty salon
beauty supply store
bed and breakfast
bicycle shop
bike repair shop
blinds and curtains store
boat dealer
bookkeeper
bookstore
bottle shop
boutique
bowling alley
boxing gym
breakfast restaurant
brewery
bridal shop
brunch restaurant
bubble tea shop
builder
building inspector
burger restaurant
butcher shop
cafe
cake shop
camera store
campground
car dealer
car detailing service
car hire
car rental agency
car repair shop
car wash
carpenter
carpet cleaner
carpet store
caterer
cell phone store
chemist
chicken restaurant
child care centre
childcare service
chinese restaurant
chiropractor
chocolate shop
church
cinema
cleaning service
climbing gym
clothing store
cocktail bar
coffee roaster
coffee shop
comedy club
community centre
computer repair service
computer store
concreter
conference venue
construction company
consultant
convenience store
cooking school
cosmetic clinic
cosmetic surgeon
coworking space
craft store
creperie
cupcake shop
dance school
day spa
deli
dental clinic
dentist
department store
dermatologist
dessert shop
dietitian
diner
discount store
dog groomer
dog trainer
dog walker
donut shop
driving school
dry cleaner
dumpling restaurant
early learning centre
electrician
electronics store
emergency plumber
employment agency
engineering consultant
escape room
event planner
event venue
eyebrow studio
fabric store
family lawyer
fast food restaurant
fencing contractor
financial planner
fish and chips shop
fish market
fitness studio
flooring store
florist
food truck
french restaurant
frozen yogurt shop
function centre
funeral home
furniture store
garage door supplier
garden centre
gardener
gas station
gelato shop
general practitioner
gift shop
glazier
gluten-free restaurant
golf course
greek restaurant
grocery store
gutter cleaning service
gym
hair salon
halal restaurant
handyman
hardware store
health food store
hearing clinic
heating contractor
hiking guide
home builder
home inspector
hospital
hostel
hot pot restaurant
hotel
ice cream shop
immigration lawyer
indian restaurant
insurance agency
interior designer
internet cafe
italian restaurant
japanese restaurant
jewelry store
juice bar
karaoke bar
kebab shop
kids party venue
kitchen renovator
korean restaurant
laundromat
lawn mowing service
lawyer
lebanese restaurant
library
liquor store
locksmith
lodge
magician
makeup artist
malaysian restaurant
marketing agency
martial arts school
massage therapist
mechanic
medical centre
mediterranean restaurant
mexican restaurant
middle eastern restaurant
mobile mechanic
mortgage broker
motel
movers
moving company
museum
music school
music store
nail salon
naturopath
newsagent
night club
noodle shop
nursing home
nutritionist
occupational therapist
office furniture store
optometrist
orthodontist
osteopath
paint store
painter
pancake restaurant
party supply store
pastry shop
pawn shop
pediatrician
pest control service
pet groomer
pet shop
pet sitter
pharmacy
photographer
photography studio
physiotherapist
piano teacher
pilates studio
pizza restaurant
plasterer
playground
plumber
podiatrist
pool cleaning service
pool supply store
post office
pottery studio
preschool
printing service
private school
property manager
psychologist
pub
ramen restaurant
real estate agency
recording studio
recruitment agency
removalist
resort
restaurant
roofing contractor
rug store
running store
salad bar
sandwich shop
school
seafood restaurant
second hand store
security system installer
self storage
shoe repair shop
shoe store
shopping mall
sign maker
skate shop
ski shop
skin care clinic
software company
solar panel installer
solicitor
spa
speech pathologist
sports bar
sports club
sporting goods store
stationery store
steakhouse
storage facility
supermarket
surf school
sushi restaurant
swimming pool
swimming school
tailor
takeaway restaurant
tattoo studio
tax agent
taxi service
tea house
thai restaurant
theatre
thrift store
tiler
tire shop
toy store
travel agency
tree service
turkish restaurant
tutoring service
tyre shop
university
upholsterer
urgent care clinic
used car dealer
vegan restaurant
vegetarian restaurant
veterinarian
video game store
vietnamese restaurant
vintage store
water damage restoration service
web designer
wedding photographer
wedding venue
window cleaning service
wine bar
winery
yoga studio
""".strip().splitlines()))


# What people type -> the categories they mean (search engines call this
# query expansion). Keys are matched as words/prefixes.
SYNONYMS: dict[str, list[str]] = {
    "doctor": ["general practitioner", "medical centre"], "gp": ["general practitioner", "medical centre"],
    "mechanic": ["mechanic", "car repair shop", "mobile mechanic"], "car service": ["car repair shop", "mechanic"],
    "hairdresser": ["hair salon", "barber shop"], "haircut": ["barber shop", "hair salon"],
    "chemist": ["pharmacy", "chemist"], "vet": ["veterinarian", "animal hospital"],
    "chicken": ["chicken restaurant", "fast food restaurant"], "fish": ["fish and chips shop", "seafood restaurant", "fish market"],
    "chips": ["fish and chips shop"], "takeaway": ["takeaway restaurant", "fast food restaurant"],
    "lawyer": ["lawyer", "solicitor", "family lawyer"], "attorney": ["lawyer"], "physio": ["physiotherapist"],
    "chiro": ["chiropractor"], "dental": ["dentist", "dental clinic"], "teeth": ["dentist"],
    "nails": ["nail salon"], "lashes": ["beauty salon", "eyebrow studio"], "brows": ["eyebrow studio"],
    "tutor": ["tutoring service"], "tuition": ["tutoring service"], "childcare": ["child care centre", "early learning centre"],
    "daycare": ["child care centre"], "kinder": ["preschool", "early learning centre"],
    "phone repair": ["cell phone store", "computer repair service"], "phone": ["cell phone store"],
    "laptop": ["computer repair service", "computer store"], "aircon": ["air conditioning contractor"],
    "ac": ["air conditioning contractor"], "sparky": ["electrician"], "tradie": ["handyman", "builder"],
    "removals": ["removalist", "moving company"], "real estate": ["real estate agency"], "agent": ["real estate agency"],
    "accountant": ["accounting firm", "tax agent", "bookkeeper"], "tax": ["tax agent"],
    "gym": ["gym", "fitness studio"], "fitness": ["gym", "fitness studio", "pilates studio", "yoga studio"],
    "coffee": ["cafe", "coffee shop"], "brunch": ["brunch restaurant", "cafe"], "pizza": ["pizza restaurant"],
    "burger": ["burger restaurant"], "sushi": ["sushi restaurant", "japanese restaurant"],
    "bottle-o": ["bottle shop"], "liquor": ["liquor store", "bottle shop"], "grocer": ["grocery store"],
    "tyres": ["tyre shop"], "tires": ["tire shop"], "photographer": ["photographer", "wedding photographer"],
}


def _typo_match(q: str, c: str) -> bool:
    try:
        from search_engine import coverage, tokens
    except Exception:
        return False
    qt = tokens(q, keep_stopwords=True)
    return bool(qt) and coverage(qt, tokens(c, keep_stopwords=True)) >= 1.0


def search_categories(query: str, limit: int = 8) -> list[str]:
    """Ranked like a search box: exact, starts-with, a word starts-with,
    synonyms ("doctor" -> "general practitioner"), then typo-tolerant
    matches ("resturant" -> "restaurant"), then plain substring."""
    q = " ".join((query or "").strip().lower().split())
    if len(q) < 2 or len(q) > 100:
        return []
    exact, prefix, word_prefix, contains, typo = [], [], [], [], []
    for c in CATEGORIES:
        if c == q:
            exact.append(c)
        elif c.startswith(q):
            prefix.append(c)
        elif any(w.startswith(q) for w in c.split()) or (" " in q and all(any(w.startswith(p) for w in c.split()) for p in q.split())):
            word_prefix.append(c)
        elif q in c:
            contains.append(c)
        elif len(q) >= 4 and _typo_match(q, c):
            typo.append(c)
    synonyms = []
    for key, cats in SYNONYMS.items():
        if key == q or (len(q) >= 3 and key.startswith(q)) or q.startswith(key + " ") or f" {key}" in f" {q}":
            synonyms += cats
    typo.sort(key=len)  # "restaurant" before "asian restaurant"
    ordered = exact + prefix + word_prefix + synonyms + typo + contains
    out, seen = [], set()
    for c in ordered:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:limit]


def guess_from_name(name: str) -> str:
    """Category from the name itself ("Sparkle Car Wash" -> "car wash")."""
    import re
    low = " " + re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()) + " "
    best = ""
    for c in CATEGORIES:
        if f" {c} " in low and len(c) > len(best):
            best = c
    if best:
        return best
    for word, cat in (("cafe", "cafe"), ("coffee", "cafe"), ("dental", "dentist"), ("pizza", "pizza restaurant"),
                      ("sushi", "sushi restaurant"), ("seafood", "seafood restaurant"), ("fish", "fish and chips shop"),
                      ("barber", "barber shop"), ("hair", "hair salon"), ("nails", "nail salon"), ("plumb", "plumber"),
                      ("electric", "electrician"), ("physio", "physiotherapist"), ("vet", "veterinarian"),
                      ("wash", "car wash"), ("auto", "car repair shop"), ("motor", "car repair shop"),
                      ("bakery", "bakery"), ("kebab", "kebab shop"), ("burger", "burger restaurant"), ("chicken", "chicken restaurant"), ("ramen", "ramen restaurant"),
                      ("indian", "indian restaurant"), ("italian", "italian restaurant"), ("chinese", "chinese restaurant"),
                      ("dumpling", "dumpling restaurant"), ("gelato", "gelato shop"), ("donut", "donut shop"), ("brew", "brewery"),
                      ("thai", "thai restaurant"), ("gym", "gym"), ("tutor", "tutoring service"),
                      ("school", "school"), ("clinic", "medical centre"), ("pharmacy", "pharmacy")):
        if re.search(r"\b" + word, low):
            return cat
    return ""


# Categories too broad to test usefully: "best restaurant in North Ryde" is
# a question big venues win; customers of a burger shop ask for burgers.
GENERIC_CATEGORIES = {
    "restaurant", "restaurants", "food", "eatery", "takeaway", "takeaway restaurant", "fast food",
    "fast food restaurant", "shop", "store", "retail", "business", "service", "services", "clinic",
    "health", "medical", "salon", "point of interest", "establishment", "company", "contractor",
}


def refine_category(name: str, category: str) -> tuple[str, str | None]:
    """("The Burger Boys", "restaurant") -> ("burger restaurant", note).
    Only ever narrows a generic category using the business's own name;
    anything already specific is left exactly as the user gave it."""
    cat = " ".join((category or "").split())
    if cat.lower() not in GENERIC_CATEGORIES:
        return cat, None
    guess = guess_from_name(name)
    if not guess or guess.lower() == cat.lower() or guess.lower() in GENERIC_CATEGORIES:
        return cat, None
    from category_match import compare
    if compare(cat, guess)["verdict"] == "mismatch":
        return cat, None
    return guess, (f"Checked as \u201c{guess}\u201d rather than \u201c{cat}\u201d (from the business name) -- "
                   f"customers ask for the specific thing, and broad questions favour big venues.")
