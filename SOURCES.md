# Sources & data

maritimeint's detection heuristics and risk model are grounded in real, authoritative
maritime-domain-awareness sources. This page lists the **primary sources** behind the
tool and the **real datasets/feeds** you can wire it to. (The bundled `demos/` files are
synthetic, clearly labeled — production use should draw on the feeds below.)

> Verify licensing/terms on each source before redistributing its data. Open vs.
> commercial is noted per entry.

## 1. Sanctions & designations — what to screen against (real, authoritative)
- **OFAC SDN List** (US Treasury) — designates vessels by **IMO number**; the canonical
  US sanctions data. Open. https://sanctionssearch.ofac.treas.gov · https://ofac.treasury.gov/sanctions-list-service
- **EU Consolidated Financial Sanctions List** — open. https://www.sanctionsmap.eu
- **UK OFSI Consolidated List** — open. https://www.gov.uk/government/publications/financial-sanctions-consolidated-list-of-targets
- **UANI "Ghost Armada" Iran tanker tracker** — curated list of tankers tied to sanctioned
  Iranian oil trade (IMO/MMSI). Open. https://www.unitedagainstnucleariran.com/tanker-tracker

## 2. AIS — real vessel position & identity data (the behavioral layer)
- **AISHub** — community AIS feed exchange (NMEA). Open (contribute-to-access).
  https://www.aishub.net
- **Spire Maritime** — satellite + terrestrial AIS (absorbed exactEarth). Commercial.
  https://spire.com/maritime · docs: https://documentation.spire.com/ais-fundamentals/
- **IMO SOLAS V/19** — the carriage rule that makes an AIS *gap* a signal (AIS must be on
  "at all times" barring logged safety exceptions). https://www.imo.org/en/OurWork/Safety/Pages/AIS.aspx

## 3. Dark-vessel detection — satellite (real imagery for non-broadcasting ships)
- **Copernicus Sentinel-1 (SAR)** — all-weather radar; the open workhorse for detecting
  vessels that have gone dark. Open. https://dataspace.copernicus.eu
- **Global Fishing Watch** — open AIS + SAR vessel detections; the *Nature* (2024) study
  using the full Sentinel-1 archive (~20M detections vs ~100B AIS points) found a large
  share of vessel activity absent from public AIS. Open. https://globalfishingwatch.org/data/

## 4. Vessel identity & ownership (resolve who's really behind a hull)
- **Equasis** — free registry: IMO no., flag, registered owner, ISM manager, **P&I cover**,
  class society, inspection history. Open (registration). https://www.equasis.org
- **IMO GISIS** — authoritative IMO-number registry. Open (registration). https://gisis.imo.org

## 5. Methodology & analysis (peer-reviewed / think-tank — why the heuristics work)
- **C4ADS — "Unmasked: Vessel Identity Laundering"** — the detection playbook for
  MMSI/IMO identity fraud, AIS spoofing, and flag-hopping, with case studies.
  https://c4ads.org/reports/unmasked/
- **CSIS — shadow/dark-fleet analyses** — scale, behavior, and policy context.
  https://www.csis.org
- **RUSI — countering shadow-fleet activity / flag-state reform.**
  https://www.rusi.org
- **Windward / Kpler** — industry references on deceptive shipping practices, AIS
  spoofing, and "Know Your Vessel" behavioral risk scoring. Commercial.
  https://windward.ai · https://www.kpler.com

## How maritimeint uses these
- **Detectors** (AIS gaps, spoofing, loitering, rendezvous) operate on AIS feeds from §2,
  cross-validated against SAR from §3 to separate true dark behavior from receiver coverage.
- **Sanctions screening** matches tracked vessels against §1 lists by MMSI/IMO/name.
- **Risk scoring** weights signals per the methodologies in §5 (behavioral risk, identity
  integrity, ownership/flag opacity from §4).

*Sourcing note: this list is compiled from public reporting and primary portals; confirm
each before operational use.*
