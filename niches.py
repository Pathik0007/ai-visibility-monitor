"""
Niche library: what customers of each kind of business actually ask an AI
assistant, where that kind of business needs to be listed, and the fixes
that matter most for it.

Why this exists: "best {category} in {location}" is how a marketer phrases
it, not how customers ask. Real questions carry intent -- urgency ("plumber
available tonight"), price ("how much is a check-up"), a specific service
("Invisalign"), an audience ("good with nervous patients"). Each intent is
tagged with a theme so a miss on it maps to a specific fix in the report.

Foundations (why the platforms below, not just Google):
  - Gemini answers local questions from Google Maps / Google Business
    Profile data.
  - ChatGPT does not read Google Business Profiles directly; its local
    results lean on Bing (Bing Places), business websites, publications and
    directories.
  - Claude and Perplexity search the live web: your website, directories,
    review sites and local articles.
  - Siri / Apple Maps use Apple Business Connect.
So a business needs: (1) its listings everywhere these systems read,
(2) reviews on the platforms its customers use, (3) a website that says
clearly what it does and where -- and that AI search crawlers may read.
"""

from __future__ import annotations
import re

PILLARS = {
    "listings": "Listings & profiles",
    "reviews": "Reviews & reputation",
    "website": "Website",
    "mentions": "Articles & mentions",
}

# Everyone needs these -- each feeds a different assistant.
CORE_PLATFORMS = [
    {"name": "Google Business Profile", "url": "https://business.google.com", "why": "Gemini and Google's AI answers read it"},
    {"name": "Bing Places", "url": "https://www.bingplaces.com", "why": "ChatGPT and Copilot lean on Bing for local results"},
    {"name": "Apple Business Connect", "url": "https://businessconnect.apple.com", "why": "Siri and Apple Maps"},
]

# General directories assistants commonly cite, by country.
REGIONAL_DIRECTORIES = {
    "AU": ["Yellow Pages", "TrueLocal", "Facebook"],
    "NZ": ["Yellow NZ", "Facebook"],
    "US": ["Yelp", "Better Business Bureau", "Facebook", "Nextdoor"],
    "CA": ["Yelp", "Yellow Pages Canada", "Facebook"],
    "UK": ["Yell", "Trustpilot", "Facebook"],
    "*": ["Facebook", "Yelp"],
}

PLATFORM_URLS = {
    "Yellow Pages": "https://www.yellowpages.com.au", "TrueLocal": "https://www.truelocal.com.au",
    "Yelp": "https://biz.yelp.com", "Better Business Bureau": "https://www.bbb.org", "Nextdoor": "https://business.nextdoor.com",
    "Yell": "https://www.yell.com", "Trustpilot": "https://business.trustpilot.com", "Facebook": "https://www.facebook.com/pages/create",
    "TripAdvisor": "https://www.tripadvisor.com/Owners", "OpenTable": "https://restaurant.opentable.com",
    "Uber Eats": "https://merchants.ubereats.com", "DoorDash": "https://get.doordash.com", "Menulog": "https://www.menulog.com.au/restaurant-signup",
    "HotDoc": "https://www.hotdoc.com.au", "HealthEngine": "https://healthengine.com.au", "Zocdoc": "https://www.zocdoc.com/join",
    "Healthgrades": "https://update.healthgrades.com", "Doctify": "https://www.doctify.com",
    "hipages": "https://hipages.com.au", "ServiceSeeking": "https://www.serviceseeking.com.au", "Oneflare": "https://www.oneflare.com.au",
    "Angi": "https://www.angi.com/pros", "Thumbtack": "https://www.thumbtack.com/pro", "Checkatrade": "https://www.checkatrade.com",
    "TrustATrader": "https://www.trustatrader.com", "Rated People": "https://www.ratedpeople.com", "Houzz": "https://www.houzz.com/pro",
    "Fresha": "https://www.fresha.com/for-business", "Treatwell": "https://www.treatwell.co.uk/partners", "Booksy": "https://biz.booksy.com",
    "ClassPass": "https://classpass.com/partners", "Mindbody": "https://www.mindbodyonline.com",
    "Avvo": "https://www.avvo.com/for-lawyers", "Justia": "https://lawyers.justia.com", "Law Society find-a-solicitor": "",
    "realestate.com.au": "https://www.realestate.com.au", "Domain": "https://www.domain.com.au", "RateMyAgent": "https://www.ratemyagent.com.au",
    "Zillow": "https://www.zillow.com/agent-resources", "Rightmove": "https://www.rightmove.co.uk",
    "Booking.com": "https://join.booking.com", "Airbnb": "https://www.airbnb.com/host", "Expedia": "https://apps.expediapartnercentral.com",
    "Care for Kids": "https://www.careforkids.com.au", "StartingBlocks": "https://www.startingblocks.gov.au",
    "Care.com": "https://www.care.com", "Rover": "https://www.rover.com/become-a-sitter",
    "carsales": "https://www.carsales.com.au", "MyCarSpace": "", "RepairPal": "https://repairpal.com/shops",
    "Word of Mouth": "https://www.wordofmouth.com.au", "Productreview.com.au": "https://www.productreview.com.au",
}

# Shared question openers -- always asked first so every report has the
# headline "best X" signal, then niche intents follow.
CORE_QUESTIONS = [
    ("What's the best {noun} in {location}?", "best_of"),
    ("Can you recommend a good {noun} near {location}?", "recommendation"),
]

NICHES: list[dict] = [
    # ---------------- food & drink ----------------
    {"key": "cafe", "label": "Cafés", "group": "food",
     "match": r"\b(cafe|café|coffee|brunch|breakfast)",
     "questions": [("Where can I get great coffee and brunch in {location}?", "specialty"),
                   ("Which cafe in {location} is good for working on a laptop?", "audience"),
                   ("Is there a cafe in {location} open early on weekends?", "hours"),
                   ("Kid-friendly cafe in {location} with good food?", "audience"),
                   ("Which cafe in {location} has the best reviews?", "reviews"),
                   ("Cafe in {location} with good vegan or gluten-free options?", "specialty")],
     "platforms": {"AU": ["Word of Mouth", "TripAdvisor"], "US": ["Yelp", "TripAdvisor"], "UK": ["TripAdvisor"], "*": ["TripAdvisor"]},
     "fixes": [("listings", "Put your full menu, prices and opening hours on Google and your website -- assistants quote these directly."),
               ("reviews", "Ask regulars to mention what they order (“the best flat white”, “great smashed avo”) -- assistants repeat specific praise."),
               ("mentions", "Pitch local “best brunch in {location}” roundups and food Instagram accounts; these lists are what assistants cite.")]},
    {"key": "takeaway", "label": "Takeaway & fast food", "group": "food",
     "match": r"\b(burgers?|pizz\w*|kebabs?|fish and chips|fried chicken|chicken|takeaway|fast food|hot ?dogs?|tacos?)",
     "questions": [("Where can I get the best {noun_short} in {location}?", "specialty"),
                   ("Good {noun} open late in {location}?", "hours"),
                   ("Cheap and good {noun} in {location}?", "price"),
                   ("Which {noun} in {location} delivers?", "booking"),
                   ("Which {noun} in {location} has the best reviews?", "reviews"),
                   ("{noun_cap} in {location} good for a group or family?", "audience")],
     "platforms": {"AU": ["Uber Eats", "DoorDash", "Menulog", "Word of Mouth"], "US": ["Uber Eats", "DoorDash", "Yelp"],
                   "UK": ["Uber Eats", "Deliveroo", "Just Eat"], "*": ["Uber Eats", "DoorDash"]},
     "fixes": [("listings", "Be on the delivery apps your area uses, with the same name, photos and menu as Google -- assistants cite these listings."),
               ("reviews", "Ask for reviews that name the item (“best smash burger in Ryde”) -- that wording is exactly what gets repeated back."),
               ("website", "Put a plain-text menu with prices on your own site (not just a PDF or image) so AI search can read it.")]},
    {"key": "restaurant", "label": "Restaurants", "group": "food",
     "match": r"\b(restaurants?|bistro|eatery|diner|steakhouse|sushi|ramen|dumplings?|thai|indian|italian|chinese|japanese|korean|vietnamese|mexican|lebanese|turkish|greek|seafood|grill|bbq|barbecue)",
     "questions": [("Best {noun} for dinner in {location}?", "specialty"),
                   ("Good {noun} in {location} for a date night?", "audience"),
                   ("Affordable {noun} in {location} that's actually good?", "price"),
                   ("{noun_cap} in {location} that takes bookings for large groups?", "booking"),
                   ("Which {noun} in {location} has the best reviews?", "reviews"),
                   ("{noun_cap} in {location} with vegetarian or gluten-free options?", "specialty")],
     "platforms": {"AU": ["OpenTable", "TripAdvisor", "Word of Mouth"], "US": ["OpenTable", "Yelp", "TripAdvisor"],
                   "UK": ["OpenTable", "TripAdvisor"], "*": ["TripAdvisor", "OpenTable"]},
     "fixes": [("listings", "Add your menu, price range, cuisine and booking link to Google, TripAdvisor and OpenTable."),
               ("reviews", "Encourage reviews that name dishes and occasions (“birthday dinner”, “best pad thai”)."),
               ("mentions", "Get into local food guides and “best {noun} in {location}” articles -- the pages assistants learn from."),
               ("website", "Add Restaurant structured data (cuisine, price range, hours) and a text menu to your website.")]},
    {"key": "bar", "label": "Bars & pubs", "group": "food",
     "match": r"\b(bars?|pubs?|wine bar|cocktail|brewery|tavern)\b",
     "questions": [("Best bar in {location} for after-work drinks?", "audience"),
                   ("Pub in {location} with good food and a beer garden?", "specialty"),
                   ("Where's good for cocktails in {location}?", "specialty"),
                   ("Bar in {location} that's open late?", "hours"),
                   ("Which pub in {location} shows live sport?", "specialty"),
                   ("Which bar in {location} has the best reviews?", "reviews")],
     "platforms": {"*": ["TripAdvisor"], "AU": ["TripAdvisor", "Word of Mouth"], "US": ["Yelp", "TripAdvisor"]},
     "fixes": [("listings", "List happy hours, live music/sport, and food on Google and Facebook events."),
               ("reviews", "Ask for reviews that mention the vibe and occasion (“perfect for after-work drinks”).")]},
    {"key": "bakery", "label": "Bakeries & desserts", "group": "food",
     "match": r"\b(bakery|bakeries|cakes?|patisserie|donuts?|gelato|ice cream|desserts?|cupcakes?)",
     "questions": [("Best bakery in {location} for fresh bread and pastries?", "specialty"),
                   ("Where can I order a custom birthday cake in {location}?", "specialty"),
                   ("{noun_cap} in {location} open early?", "hours"),
                   ("Which {noun} in {location} has the best reviews?", "reviews")],
     "platforms": {"*": ["Uber Eats"], "AU": ["Uber Eats", "Word of Mouth"]},
     "fixes": [("website", "Have a page for custom/celebration cakes with prices and order lead times -- it's a common question.")]},
    # ---------------- health ----------------
    {"key": "dentist", "label": "Dental practices", "group": "health",
     "match": r"\b(dentists?|dental|orthodont\w*|endodont\w*|periodont\w*)",
     "questions": [("Which dentist in {location} is good for nervous patients?", "audience"),
                   ("Is there an emergency dentist open on weekends in {location}?", "urgent"),
                   ("How much does a check-up and clean cost in {location}, and which dentist is good value?", "price"),
                   ("Best dentist in {location} for Invisalign or teeth straightening?", "specialty"),
                   ("Which dentist in {location} has the best reviews?", "reviews"),
                   ("Family dentist in {location} that's good with kids?", "audience")],
     "platforms": {"AU": ["HotDoc", "HealthEngine"], "US": ["Zocdoc", "Healthgrades"], "UK": ["Doctify"], "*": []},
     "fixes": [("listings", "List every treatment you offer (implants, Invisalign, emergency) as a Google service, with online booking enabled."),
               ("website", "Give each key treatment its own page with prices or a price range and an FAQ -- assistants answer cost questions from these."),
               ("reviews", "Ask patients to mention the treatment and how they felt (“great with my anxiety”) in reviews.")]},
    {"key": "gp", "label": "Medical centres & GPs", "group": "health",
     "match": r"\b(doctors?|gp|general practi\w+|medical cent\w+|medical clinic|family medicine|urgent care)",
     "questions": [("Which medical centre in {location} has same-day appointments?", "urgent"),
                   ("Bulk-billing doctor in {location} taking new patients?", "price"),
                   ("Good female GP in {location}?", "audience"),
                   ("Medical centre open on weekends in {location}?", "hours"),
                   ("Which GP clinic in {location} has the best reviews?", "reviews")],
     "platforms": {"AU": ["HotDoc", "HealthEngine"], "US": ["Zocdoc", "Healthgrades"], "UK": ["Doctify"], "*": []},
     "fixes": [("listings", "Keep hours, billing policy and “new patients welcome” up to date on Google and your booking platform."),
               ("website", "List each doctor with their interests (women's health, kids, skin checks) -- assistants match these to questions.")]},
    {"key": "allied", "label": "Physio, chiro & allied health", "group": "health",
     "match": r"\b(physio\w*|chiropract\w*|osteopath\w*|podiatr\w*|massage therap\w*|myotherap\w*|occupational therap\w*|speech path\w*|dietitian|nutritionist|acupunct\w*|psycholog\w*|counsell?\w*)",
     "questions": [("Best {noun} in {location} for back pain?", "specialty"),
                   ("{noun_cap} in {location} that does sports injuries?", "specialty"),
                   ("{noun_cap} in {location} with weekend or evening appointments?", "hours"),
                   ("Which {noun} in {location} has the best reviews?", "reviews"),
                   ("Does any {noun} in {location} offer health-fund rebates on the spot?", "price")],
     "platforms": {"AU": ["HotDoc", "HealthEngine"], "US": ["Zocdoc", "Healthgrades"], "UK": ["Doctify"], "*": []},
     "fixes": [("website", "Create a page per condition you treat (back pain, sports injuries, headaches) -- assistants match condition questions to these."),
               ("reviews", "Ask patients to name the condition you helped with in their review.")]},
    {"key": "optometrist", "label": "Optometrists", "group": "health",
     "match": r"\b(optometr\w*|optician|eye care|eyewear)",
     "questions": [("Good optometrist in {location} for kids' eye tests?", "audience"),
                   ("Where can I get an eye test today in {location}?", "urgent"),
                   ("Optometrist in {location} with affordable glasses?", "price"),
                   ("Which optometrist in {location} has the best reviews?", "reviews")],
     "platforms": {"AU": ["HotDoc", "HealthEngine"], "US": ["Zocdoc"], "*": []},
     "fixes": [("listings", "Show bulk-billed eye tests / insurance accepted and online booking on Google.")]},
    {"key": "vet", "label": "Vets & pet care", "group": "pets",
     "match": r"\b(vets?|veterinar\w*|animal hospital|pet groom\w*|dog groom\w*|groomers?|dog train\w*|pet sitt\w*|dog walk\w*|kennels?)",
     "questions": [("Is there an emergency vet open now in {location}?", "urgent"),
                   ("Which {noun} in {location} is good with anxious dogs?", "audience"),
                   ("How much does a {noun} visit cost in {location}?", "price"),
                   ("Which {noun} in {location} has the best reviews?", "reviews")],
     "platforms": {"AU": ["Yellow Pages"], "US": ["Yelp", "Rover"], "*": []},
     "fixes": [("listings", "Make after-hours/emergency arrangements explicit on Google and your website -- the most-asked vet question."),
               ("reviews", "Ask owners to mention their pet and treatment in reviews.")]},
    # ---------------- beauty ----------------
    {"key": "barber", "label": "Barbers", "group": "beauty",
     "match": r"\bbarber",
     "questions": [("Best barber in {location} for a skin fade?", "specialty"),
                   ("Barber in {location} that takes walk-ins?", "booking"),
                   ("Barber in {location} open on Sundays?", "hours"),
                   ("Cheap but good barber in {location}?", "price"),
                   ("Which barber in {location} has the best reviews?", "reviews")],
     "platforms": {"*": ["Fresha", "Booksy"], "UK": ["Booksy", "Treatwell"]},
     "fixes": [("listings", "Turn on online booking and say “walk-ins welcome” (if true) on Google -- the two things people ask."),
               ("website", "Post a price list and photos of cuts on your site and Instagram.")]},
    {"key": "hair", "label": "Hair salons", "group": "beauty",
     "match": r"\b(hair\w*|blow ?dry|colou?rist)",
     "questions": [("Hair salon in {location} good at balayage or blonde colour?", "specialty"),
                   ("{noun_cap} in {location} good with curly hair?", "specialty"),
                   ("{noun_cap} in {location} with appointments this week?", "booking"),
                   ("Affordable {noun} in {location}?", "price"),
                   ("Which {noun} in {location} has the best reviews?", "reviews")],
     "platforms": {"*": ["Fresha", "Booksy"], "UK": ["Treatwell", "Fresha"], "AU": ["Fresha"]},
     "fixes": [("listings", "Turn on online booking (Fresha/Booksy/your system) and link it from Google -- “can I book now” is a top question."),
               ("website", "Show a price list and photos of your specialty work (fades, balayage) on your site and Instagram.")]},
    {"key": "beauty", "label": "Nails, beauty & spa", "group": "beauty",
     "match": r"\b(nails?|beauty|spa|lash\w*|brows?|eyebrow|waxing|facials?|skin ?care|cosmetic|tanning|massage)",
     "questions": [("{noun_cap} in {location} with same-day appointments?", "booking"),
                   ("{noun_cap} in {location} that sells gift vouchers?", "audience"),
                   ("Clean, hygienic {noun} in {location}?", "reviews"),
                   ("Affordable {noun} in {location}?", "price"),
                   ("Which {noun} in {location} has the best reviews?", "reviews")],
     "platforms": {"*": ["Fresha"], "UK": ["Treatwell", "Fresha"], "AU": ["Fresha"]},
     "fixes": [("listings", "List every service with prices on your booking platform and Google services list."),
               ("website", "Have gift-voucher and price pages -- assistants answer “where can I buy a spa voucher” from them.")]},
    # ---------------- fitness ----------------
    {"key": "fitness", "label": "Gyms & fitness studios", "group": "fitness",
     "match": r"\b(gym|fitness|pilates|yoga|crossfit|boxing|martial arts|personal train\w*|bootcamp|swim school|dance studio)",
     "questions": [("Best {noun} in {location} for beginners?", "audience"),
                   ("{noun_cap} in {location} with a free trial class?", "price"),
                   ("{noun_cap} in {location} with early morning or evening sessions?", "hours"),
                   ("How much is a {noun} membership in {location}?", "price"),
                   ("Which {noun} in {location} has the best reviews?", "reviews")],
     "platforms": {"*": ["ClassPass", "Mindbody"]},
     "fixes": [("website", "Publish membership prices and a timetable as text -- “how much” and “when” are what people ask."),
               ("listings", "Mention beginner-friendly classes and free trials on Google.")]},
    # ---------------- trades ----------------
    {"key": "urgent_trade", "label": "Emergency trades (plumbers, electricians, locksmiths)", "group": "trades",
     "match": r"\b(plumb\w*|electrici\w*|locksmith\w*|air ?con\w*|hvac|gas fitt\w*|hot water|drain\w*)",
     "questions": [("Who's a reliable {noun} in {location} available today?", "urgent"),
                   ("Emergency {noun} in {location} open 24/7?", "urgent"),
                   ("How much does a {noun} charge per hour in {location}, and who's good value?", "price"),
                   ("Licensed {noun} in {location} with good reviews?", "reviews"),
                   ("{noun_cap} in {location} that gives upfront quotes?", "price"),
                   ("Which {noun} in {location} do locals trust?", "reviews")],
     "platforms": {"AU": ["hipages", "ServiceSeeking", "Oneflare"], "US": ["Angi", "Thumbtack", "Yelp"],
                   "UK": ["Checkatrade", "TrustATrader", "Rated People"], "*": []},
     "fixes": [("listings", "Set your service area, after-hours availability and “emergency” service on Google and Bing -- urgency questions are the money questions."),
               ("website", "Have a page per job type (blocked drains, hot water, switchboards) naming the suburbs you cover, with your licence number."),
               ("reviews", "Ask customers to mention the job and how fast you arrived (“fixed our burst pipe within an hour”).")]},
    {"key": "project_trade", "label": "Builders & renovators", "group": "trades",
     "match": r"\b(builders?|building|renovat\w*|carpent\w*|roof\w*|painters?|painting|tiler|tiling|concret\w*|fenc\w*|kitchens?|bathrooms?|landscap\w*|pool builder|handyman|joiner\w*|plaster\w*)",
     "questions": [("Recommended {noun} in {location} for a home renovation?", "specialty"),
                   ("How much does a {noun} cost in {location}?", "price"),
                   ("Reliable {noun} in {location} that turns up on time?", "reviews"),
                   ("Licensed and insured {noun} in {location}?", "reviews"),
                   ("Which {noun} in {location} has the best reviews?", "reviews")],
     "platforms": {"AU": ["hipages", "ServiceSeeking", "Oneflare", "Houzz"], "US": ["Houzz", "Angi", "Thumbtack"],
                   "UK": ["Checkatrade", "MyBuilder", "Rated People"], "*": ["Houzz"]},
     "fixes": [("website", "Show a project gallery with suburb and job type for each job (“bathroom reno, North Ryde”), plus licence and insurance details."),
               ("reviews", "Ask for reviews that describe the project and mention reliability and cleanliness.")]},
    {"key": "home_service", "label": "Cleaners, pest control & removalists", "group": "trades",
     "match": r"\b(clean\w*|pest\w*|removal\w*|movers|moving|gardener|lawn|gutter|window clean\w*|carpet clean\w*|rubbish)",
     "questions": [("Reliable {noun} in {location} with good reviews?", "reviews"),
                   ("How much does a {noun} cost in {location}?", "price"),
                   ("{noun_cap} in {location} available this week?", "urgent"),
                   ("Eco-friendly {noun} in {location}?", "specialty"),
                   ("Which {noun} in {location} do locals recommend?", "recommendation")],
     "platforms": {"AU": ["hipages", "Airtasker", "Oneflare"], "US": ["Angi", "Thumbtack", "Nextdoor"], "UK": ["Checkatrade"], "*": []},
     "fixes": [("website", "Publish clear pricing (from-prices or per-room/per-hour) -- “how much” is the most common question."),
               ("listings", "List the exact suburbs you serve on Google and Bing, not just a radius.")]},
    # ---------------- automotive ----------------
    {"key": "car_care", "label": "Car wash & detailing", "group": "automotive",
     "match": r"\b(car wash|detailing|detailer|car clean\w*)",
     "questions": [("Best {noun} in {location} for a full interior and exterior detail?", "specialty"),
                   ("How much does a {noun} cost in {location}?", "price"),
                   ("{noun_cap} in {location} open on weekends?", "hours"),
                   ("Mobile {noun} that comes to you in {location}?", "specialty"),
                   ("Which {noun} in {location} has the best reviews?", "reviews")],
     "platforms": {"AU": ["Yellow Pages"], "US": ["Yelp"], "*": []},
     "fixes": [("website", "List packages with prices and how long each takes."),
               ("listings", "Add before/after photos to Google -- they're what people check first.")]},
    {"key": "auto", "label": "Mechanics & auto services", "group": "automotive",
     "match": r"\b(mechanics?|car repair|auto\w*|tyres?|tires?|smash repair|panel beat\w*|car service|car wash|detailing|windscreen|brakes?)",
     "questions": [("Honest {noun} in {location} that doesn't overcharge?", "reviews"),
                   ("How much does a {noun} cost in {location}?", "price"),
                   ("{noun_cap} in {location} that can fit me in today?", "urgent"),
                   ("Which {noun} in {location} has the best reviews?", "reviews")],
     "platforms": {"AU": ["Yellow Pages", "carsales"], "US": ["RepairPal", "Yelp"], "UK": ["Yell"], "*": []},
     "fixes": [("website", "List services with from-prices and the makes you specialise in."),
               ("reviews", "Ask for reviews that mention honesty and price -- trust is what car-service questions are really about.")]},
    # ---------------- professional ----------------
    {"key": "legal", "label": "Lawyers", "group": "professional",
     "match": r"\b(lawyers?|solicitors?|attorneys?|legal|conveyanc\w*|barristers?|notary)",
     "questions": [("{noun_cap} in {location} with a free first consultation?", "price"),
                   ("Which {noun} in {location} explains fees upfront?", "price"),
                   ("Affordable {noun} in {location}?", "price"),
                   ("Which {noun} in {location} has the best reviews?", "reviews")],
     "platforms": {"US": ["Avvo", "Justia"], "*": []},
     "fixes": [("website", "Give each practice area its own page with plain-English FAQs and fee information."),
               ("listings", "Keep your profile current on the law society / bar directory for your region.")]},
    {"key": "finance", "label": "Accountants & finance", "group": "professional",
     "match": r"\b(accountant\w*|accounting|tax|bookkeep\w*|mortgage|financial plann\w*|finance broker|insurance)",
     "questions": [("{noun_cap} in {location} for small business owners?", "audience"),
                   ("How much does a {noun} charge in {location}?", "price"),
                   ("Which {noun} in {location} has the best reviews?", "reviews")],
     "platforms": {"AU": ["Yellow Pages"], "*": []},
     "fixes": [("website", "Have service pages per client type (sole traders, small business, first-home buyers) with indicative fees.")]},
    {"key": "real_estate", "label": "Real estate agents", "group": "professional",
     "match": r"\b(real estate|realtor|property manag\w*|estate agent)",
     "questions": [("Best real estate agent in {location} to sell my house?", "best_of"),
                   ("Which agency in {location} gets the best sale prices?", "reviews"),
                   ("Good property manager in {location}?", "specialty"),
                   ("Real estate agent in {location} with lowest commission?", "price")],
     "platforms": {"AU": ["realestate.com.au", "Domain", "RateMyAgent"], "US": ["Zillow"], "UK": ["Rightmove"], "*": []},
     "fixes": [("reviews", "Collect reviews on RateMyAgent / Zillow with sale results -- assistants cite agent comparison sites."),
               ("website", "Publish recent sales with suburb and result -- proof assistants can quote.")]},
    # ---------------- education & childcare ----------------
    {"key": "childcare", "label": "Childcare & early learning", "group": "education",
     "match": r"\b(child ?care|early learning|daycare|preschool|kindergarten|kinder|creche|nursery)",
     "questions": [("Best childcare centre in {location} with vacancies?", "booking"),
                   ("How much does daycare cost per day in {location}?", "price"),
                   ("Childcare in {location} with good reviews from parents?", "reviews"),
                   ("Early learning centre in {location} with long hours?", "hours")],
     "platforms": {"AU": ["Care for Kids", "StartingBlocks"], "US": ["Care.com"], "*": []},
     "fixes": [("listings", "Keep vacancies and fees current on Care for Kids / StartingBlocks (or your country's equivalent) and Google.")]},
    {"key": "tutoring", "label": "Tutoring & lessons", "group": "education",
     "match": r"\b(tutor\w*|tuition|coaching college|driving school|music school|music lessons?|piano|swim\w* lessons?|language school|dance school)",
     "questions": [("{noun_cap} in {location} for beginners?", "audience"),
                   ("How much does a {noun} cost per hour in {location}?", "price"),
                   ("{noun_cap} in {location} with good results?", "reviews"),
                   ("{noun_cap} in {location} with weekend lessons?", "hours")],
     "platforms": {"*": []},
     "fixes": [("website", "Show subjects/levels, prices and results (with permission) -- “good results” questions need evidence to cite.")]},
    # ---------------- accommodation & venues ----------------
    {"key": "accommodation", "label": "Hotels & stays", "group": "accommodation",
     "match": r"\b(hotels?|motels?|hostels?|resorts?|bed and breakfast|b&b|guest ?house|serviced apartment|inn|lodge)",
     "questions": [("Best place to stay in {location} for a weekend?", "best_of"),
                   ("Affordable hotel in {location} with parking?", "price"),
                   ("Family-friendly accommodation in {location}?", "audience"),
                   ("Which hotel in {location} has the best reviews?", "reviews")],
     "platforms": {"*": ["Booking.com", "TripAdvisor", "Expedia", "Airbnb"]},
     "fixes": [("listings", "Keep amenities (parking, pool, pets) identical across Booking.com, TripAdvisor and Google -- assistants filter on them.")]},
    {"key": "venue", "label": "Venues & entertainment", "group": "entertainment",
     "match": r"\b(venue|function cent\w*|wedding|event space|escape room|bowling|karaoke|cinema|theatre|gallery|museum)",
     "questions": [("Best {noun} in {location} for a birthday party?", "audience"),
                   ("Affordable {noun} in {location} for a work function?", "price"),
                   ("Which {noun} in {location} has the best reviews?", "reviews")],
     "platforms": {"*": ["TripAdvisor"]},
     "fixes": [("website", "Publish capacity, packages and prices -- planners ask assistants exactly these.")]},
    # ---------------- retail ----------------
    {"key": "retail", "label": "Shops", "group": "retail",
     "match": r"\b(store|shop|boutique|florist|grocer\w*|bottle shop|liquor|pharmacy|chemist|hardware|jewell?er\w*|bookstore|gift)",
     "questions": [("Where's a good {noun} in {location} with friendly service?", "specialty"),
                   ("{noun_cap} in {location} open on Sunday?", "hours"),
                   ("Which {noun} in {location} has the best reviews?", "reviews")],
     "platforms": {"AU": ["Productreview.com.au"], "*": []},
     "fixes": [("listings", "Add your product categories and brands to Google -- assistants answer “where can I buy X” from them.")]},
]

_COMPILED = [(n, re.compile(n["match"], re.I)) for n in NICHES]


def niche_for(category: str) -> dict | None:
    c = category or ""
    for n, rx in _COMPILED:
        if rx.search(c):
            return n
    return None


def region_code(country: str | None) -> str:
    cc = (country or "").upper()
    return {"GB": "UK"}.get(cc, cc) or "*"


def platforms_for(niche: dict | None, country: str | None) -> list[dict]:
    """Where this business should be listed, most important first."""
    region = region_code(country)
    names: list[str] = []
    if niche:
        p = niche.get("platforms") or {}
        names += p.get(region) or p.get("*") or []
    names += REGIONAL_DIRECTORIES.get(region, REGIONAL_DIRECTORIES["*"])
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append({"name": n, "url": PLATFORM_URLS.get(n, "")})
    return out


def fill(template: str, noun: str, location: str) -> str:
    short = re.sub(r"\s+(restaurant|shop|store|service|centre|center|clinic|studio|salon)$", "", noun).strip() or noun
    q = template.format(noun=noun, noun_short=short, noun_cap=noun[:1].upper() + noun[1:], location=location)
    # "Emergency emergency plumber" -> "Emergency plumber"
    q = re.sub(r"\b(\w+)\s+\1\b", r"\1", q, flags=re.I)
    return re.sub(r"\b([Aa]) ([aeiouAEIOU])", r"\1n \2", q)  # "a emergency" -> "an emergency"


def niche_questions(niche: dict | None, noun: str, location: str) -> list[tuple[str, str]]:
    qs = [(fill(t, noun, location), th) for t, th in CORE_QUESTIONS]
    for t, th in (niche or {}).get("questions", []):
        q = fill(t, noun, location)
        if q not in [x for x, _ in qs]:
            qs.append((q, th))
    return qs
