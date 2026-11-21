"""Franchises shown on the Collections page.

Two sources, both by TMDb id:
- "collections": one or more TMDb collections (Harry Potter is one collection).
- "movies": a hand-made list of movie ids, for franchises that TMDb splits into many collections
  (Marvel has about ten).

The ids are checked against TMDb at runtime: an id TMDb does not know is skipped, so a wrong id
leaves a gap in one franchise and never breaks the page. When "name" is missing, the name comes
from the TMDb collection.
"""

COLLECTIONS: list[dict] = [
    {"key": "star-wars", "collections": [10]},
    {"key": "harry-potter", "collections": [1241]},
    {"key": "middle-earth", "name": "Middle-earth", "name_fr": "Terre du Milieu", "collections": [119, 121938]},
    {"key": "marvel", "name": "Marvel Cinematic Universe", "name_fr": "Univers cinématographique Marvel", "movies": [
        1726, 1724, 10138, 10195, 1771, 24428, 68721, 76338, 100402, 118340, 99861, 102899, 271110,
        284052, 283995, 315635, 284053, 284054, 299536, 363088, 299537, 299534, 429617, 497698,
        566525, 524434, 634649, 453395, 616037, 505642, 640146, 447365,
    ]},
    {"key": "james-bond", "collections": [645]},
    {"key": "indiana-jones", "collections": [84]},
    {"key": "jurassic-park", "collections": [328]},
    {"key": "the-matrix", "collections": [2344]},
    {"key": "toy-story", "collections": [10194]},
    {"key": "back-to-the-future", "collections": [264]},
    {"key": "terminator", "collections": [528]},
    {"key": "alien", "collections": [8091]},
    {"key": "rocky", "collections": [1575]},
    {"key": "godfather", "collections": [230]},
    {"key": "mission-impossible", "collections": [87359]},
    {"key": "fast-furious", "collections": [9485]},
    {"key": "pirates-of-the-caribbean", "collections": [295]},
    {"key": "dark-knight", "collections": [263]},
    {"key": "die-hard", "collections": [1570]},
    {"key": "mad-max", "collections": [8945]},
    {"key": "hunger-games", "collections": [131635]},
    {"key": "x-men", "collections": [748]},
]
BY_KEY = {c["key"]: c for c in COLLECTIONS}
