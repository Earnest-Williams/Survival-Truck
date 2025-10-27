# Survival Truck

*A turn-based post-collapse survival and logistics simulation.*

---

## 1. Overview

**Survival Truck** is a post-apocalyptic, ASCII-based world simulation in which the player drives a modular expedition vehicle across a persistent hex-grid world.

Each day represents a turn: travel, scavenging, trade, or repair. NPC factions and caravans act under the same simulation rules, leading to emergent politics, economies, and wars. The game emphasises logistics, decision pressure, and persistent world-building rather than combat spectacle.

---

## 2. World and Game Structure

### 2.1 Map and Sites
- **Map Type:** Semi-infinite hex grid.
- **Terrain:** plains, forest, tundra, mountain, coast, ruin, wasteland.
- **Sites:** city ruins, farms, power plants, survivor camps, factories.
- **Persistence:** each site stores exploration %, scavenged %, population, and faction control.
- **Biomes:** generated procedurally using seeded noise functions.

### 2.2 Factions and NPCs
- Factions move, trade, ally, and war using the same rules as the player.
- Each faction has an ideology, resource preference, and behaviour model.
- Relations shift through diplomacy, trade, or conflict.

### 2.3 Time and Turns
- **1 Turn = 1 Day.**
- Movement, site activity, and maintenance occur in sequence.
- Seasonal cycles affect weather, food, and travel costs.

### 2.4 Core Loop
1. Plan route and move.
2. Encounter sites or events.
3. Exploit, trade, or recruit.
4. Maintain truck and crew.
5. NPC factions act and evolve.
6. World state persists.

---

## 3. The Truck

A modular survival platform inspired by a UNIMOG, expanding into a multi-cabin convoy.

**Attributes:** power, traction, armour, storage, crew capacity, maintenance load, fuel efficiency.

**Modules:**
- Cabins (living, storage, workshop, infirmary)
- Trailers (cargo, lab, greenhouse)
- Turrets and sensors
- Radio or satellite uplinks

Each module affects weight, power, visibility, and crew workload. Width, height, and length set physical limits.

---

## 4. Site Economy and Attention Curve

Every site has a bell-shaped *attention curve* linking **time spent** to **yield per day**.

| Example Site | Curve Shape | Risk |
|---------------|--------------|------|
| Abandoned Mine | Tall, narrow | High raids |
| Farmstead | Low, wide | Sustainable |
| Military Base | Right-skewed | Heavy danger |

The longer a player stays, the higher the yield *and* the risk (raiders, disease, attention from factions).

---

## 5. Crew and Community

Crew members have:
- **Skills:** mechanics, scavenging, negotiation, medicine.
- **Traits:** brave, paranoid, selfish, loyal.
- **Needs:** food, rest, morale.
- **Relationships:** friendship, rivalry, romance.

Crew may leave, mutiny, or die. Settlements can be founded and later operate autonomously, forming federations or rebel states.

---

## 6. Resources

| Type | Examples | Notes |
|-------|-----------|-------|
| Fuel | Diesel, ethanol, methane | Drives mobility |
| Food | Canned, foraged, hunted | Spoils over time |
| Water | Clean, brackish | Purified by filters |
| Spare Parts | Metal, wiring | For repairs |
| Ammunition | Bullets, shells | Limited supply |
| Trade Goods | Textiles, medicine | For barter |
| Salvage | Electronics, plastics | For upgrades |

Decay and scarcity maintain pressure to keep moving.

---

## 7. Themes

- **Entropy:** All things decay — machines, food, morale.  
- **Persistence:** The world evolves independently.  
- **Agency:** Every tactical decision has strategic weight.  
- **Isolation:** Long travel and uncertain trust define the tone.

---

## 8. ASCII Interface

- **Strategic Map:** Hex-grid view of terrain and sites.  
- **Truck View:** ASCII schematic of vehicle modules and status.  
- **Log Feed:** Daily textual report of events.  
- **Status Panels:** Crew, resources, diplomacy, conditions.

Example map:

