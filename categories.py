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


def search_categories(query: str, limit: int = 8) -> list[str]:
    """Ranked: exact match, then starts-with, then any word starting with
    the query, then plain substring."""
    q = (query or "").strip().lower()
    if len(q) < 2 or len(q) > 100:
        return []
    exact, prefix, word_prefix, contains = [], [], [], []
    for c in CATEGORIES:
        if c == q:
            exact.append(c)
        elif c.startswith(q):
            prefix.append(c)
        elif any(w.startswith(q) for w in c.split()):
            word_prefix.append(c)
        elif q in c:
            contains.append(c)
    return (exact + prefix + word_prefix + contains)[:limit]
