# Dota 2 numbered patch heads

The [machine-readable audit](../assets/build_manifests/series_head_audit.json) has the depot IDs, manifest IDs, UTC seen times, and source links. Reviewed recipes are in the [pinned client catalog](../assets/pinned_client_catalog.json). This pass validates metadata. Steam download permissions and replay playback require a separate test.

For each series, I selected the last listed build before the next numbered release and verified that it also had the highest build ID in that window. For each required Windows depot, I selected the latest public manifest strictly before the next release's listed UTC minute. This preserves manifests carried forward from earlier updates. The build export reports minutes and the depot export reports seconds. I checked archived steam.inf against the content depot's seen time and checked any client version shown in the target title.

40 recipes were added and 6 existing series heads matched. Final 7.20e build 3500444 is available as [an importable recipe](../assets/build_manifests/client_7.20e_build_3500444.json). The app keeps build 3391106 for your working installation.

The original steam.inf files for 6.84c through 6.88f were fetched directly from their depot 373301 manifests. The audit records each manifest ID and file hash.

## Manual review

- **6.70 through 6.83** need the historical Source 1 Windows depots. The supplied exports are for Source 2.
- **7.42** remains open. Its final build requires the next numbered release.

## Build-by-build review

A dash in the title column means the export says No title. A ClientVersion title gives the Dota build version alone. The numbered release boundary and its evidence determine the gameplay patch.

| Series | Final patch | Head Steam build | Exported head title | Next numbered build | Dota version | Status |
| --- | --- | ---: | --- | ---: | ---: | --- |
| 6.79 | 6.79c | [174586](https://steamdb.info/patchnotes/174586/) | — | [6.80 176112](https://steamdb.info/patchnotes/176112/) | — | Source 1 history missing |
| 6.80 | 6.80 | [240467](https://steamdb.info/patchnotes/240467/) | — | [6.81 248172](https://steamdb.info/patchnotes/248172/) | — | Source 1 history missing |
| 6.81 | 6.81b | [386450](https://steamdb.info/patchnotes/386450/) | — | [6.82 393650](https://steamdb.info/patchnotes/393650/) | — | Source 1 history missing |
| 6.82 | 6.82c | [470506](https://steamdb.info/patchnotes/470506/) | — | [6.83 476468](https://steamdb.info/patchnotes/476468/) | — | Source 1 history missing |
| 6.83 | 6.83c | [600024](https://steamdb.info/patchnotes/600024/) | — | [6.84 608168](https://steamdb.info/patchnotes/608168/) | — | Source 1 history missing |
| 6.84 | 6.84c | [787245](https://steamdb.info/patchnotes/787245/) | — | [6.85 788939](https://steamdb.info/patchnotes/788939/) | 1058 | Added |
| 6.85 | 6.85b | [894148](https://steamdb.info/patchnotes/894148/) | — | [6.86 902132](https://steamdb.info/patchnotes/902132/) | 1192 | Added |
| 6.86 | 6.86f | [1090085](https://steamdb.info/patchnotes/1090085/) | — | [6.87 1094257](https://steamdb.info/patchnotes/1094257/) | 1381 | Added |
| 6.87 | 6.87d | [1175561](https://steamdb.info/patchnotes/1175561/) | — | [6.88 1177581](https://steamdb.info/patchnotes/1177581/) | 1489 | Added |
| 6.88 | 6.88f | [1504893](https://steamdb.info/patchnotes/1504893/) | — | [7.00 1514733](https://steamdb.info/patchnotes/1514733/) | 1805 | Added |
| 7.00 | 7.00 | [1531424](https://steamdb.info/patchnotes/1531424/) | — | [7.01 1532815](https://steamdb.info/patchnotes/1532815/) | 1842 | Added |
| 7.01 | 7.01 | [1613375](https://steamdb.info/patchnotes/1613375/) | — | [7.02 1619465](https://steamdb.info/patchnotes/1619465/) | 1913 | Added |
| 7.02 | 7.02 | [1690464](https://steamdb.info/patchnotes/1690464/) | — | [7.03 1693635](https://steamdb.info/patchnotes/1693635/) | 1961 | Added |
| 7.03 | 7.03 | [1708688](https://steamdb.info/patchnotes/1708688/) | — | [7.04 1710820](https://steamdb.info/patchnotes/1710820/) | 2001 | Added |
| 7.04 | 7.04 | [1737842](https://steamdb.info/patchnotes/1737842/) | — | [7.05 1744804](https://steamdb.info/patchnotes/1744804/) | 2017 | Added |
| 7.05 | 7.05 | [1819079](https://steamdb.info/patchnotes/1819079/) | — | [7.06 1822478](https://steamdb.info/patchnotes/1822478/) | 2109 | Added |
| 7.06 | 7.06f | [2234465](https://steamdb.info/patchnotes/2234465/) | — | [7.07 2246740](https://steamdb.info/patchnotes/2246740/) | 2455 | Added |
| 7.07 | 7.07d | [2462419](https://steamdb.info/patchnotes/2462419/) | — | [7.08 2489451](https://steamdb.info/patchnotes/2489451/) | 2666 | Added |
| 7.08 | 7.08 | [2526032](https://steamdb.info/patchnotes/2526032/) | — | [7.09 2529688](https://steamdb.info/patchnotes/2529688/) | 2685 | Added |
| 7.09 | 7.09 | [2561601](https://steamdb.info/patchnotes/2561601/) | — | [7.10 2568573](https://steamdb.info/patchnotes/2568573/) | 2694 | Added |
| 7.10 | 7.10 | [2604788](https://steamdb.info/patchnotes/2604788/) | ClientVersion 2749 | [7.11 2606768](https://steamdb.info/patchnotes/2606768/) | 2749 | Added |
| 7.11 | 7.11 | [2643485](https://steamdb.info/patchnotes/2643485/) | ClientVersion 2779 | [7.12 2645048](https://steamdb.info/patchnotes/2645048/) | 2779 | Added |
| 7.12 | 7.12 | [2667855](https://steamdb.info/patchnotes/2667855/) | ClientVersion 2817 | [7.13 2682707](https://steamdb.info/patchnotes/2682707/) | 2817 | Added |
| 7.13 | 7.13b | [2717698](https://steamdb.info/patchnotes/2717698/) | ClientVersion 2830 | [7.14 2724014](https://steamdb.info/patchnotes/2724014/) | 2830 | Added |
| 7.14 | 7.14 | [2760478](https://steamdb.info/patchnotes/2760478/) | ClientVersion 2886 | [7.15 2762339](https://steamdb.info/patchnotes/2762339/) | 2886 | Added |
| 7.15 | 7.15 | [2807894](https://steamdb.info/patchnotes/2807894/) | ClientVersion 2915 | [7.16 2810703](https://steamdb.info/patchnotes/2810703/) | 2915 | Added |
| 7.16 | 7.16 | [2843904](https://steamdb.info/patchnotes/2843904/) | ClientVersion 2947 | [7.17 2849709](https://steamdb.info/patchnotes/2849709/) | 2947 | Added |
| 7.17 | 7.17 | [2888716](https://steamdb.info/patchnotes/2888716/) | ClientVersion 2986 | [7.18 2894132](https://steamdb.info/patchnotes/2894132/) | 2986 | Added |
| 7.18 | 7.18 | [2980535](https://steamdb.info/patchnotes/2980535/) | ClientVersion 3058 | [7.19 2987543](https://steamdb.info/patchnotes/2987543/) | 3058 | Added |
| 7.19 | 7.19d | [3315977](https://steamdb.info/patchnotes/3315977/) | ClientVersion 3209 | [7.20 3320919](https://steamdb.info/patchnotes/3320919/) | 3209 | Added |
| 7.20 | 7.20e | [3500444](https://steamdb.info/patchnotes/3500444/) | ClientVersion 3323 | [7.21 3513099](https://steamdb.info/patchnotes/3513099/) | 3323 | Alternate recipe ready |
| 7.21 | 7.21d | [3856028](https://steamdb.info/patchnotes/3856028/) | ClientVersion 3500 | [7.22 3857105](https://steamdb.info/patchnotes/3857105/) | 3500 | Added |
| 7.22 | 7.22h | [4406615](https://steamdb.info/patchnotes/4406615/) | ClientVersion 3839 | [7.23 4428376](https://steamdb.info/patchnotes/4428376/) | 3839 | Added |
| 7.23 | 7.23f | [4606838](https://steamdb.info/patchnotes/4606838/) | ClientVersion 3947 | [7.24 4610052](https://steamdb.info/patchnotes/4610052/) | 3947 | Added |
| 7.24 | 7.24b | [4786139](https://steamdb.info/patchnotes/4786139/) | ClientVersion 4031 | [7.25 4788262](https://steamdb.info/patchnotes/4788262/) | 4031 | Added |
| 7.25 | 7.25c | [4907483](https://steamdb.info/patchnotes/4907483/) | ClientVersion 4099 | [7.26 4911563](https://steamdb.info/patchnotes/4911563/) | 4099 | Added |
| 7.26 | 7.26c | [5222216](https://steamdb.info/patchnotes/5222216/) | ClientVersion 4312 | [7.27 5226294](https://steamdb.info/patchnotes/5226294/) | 4312 | Added |
| 7.27 | 7.27d | [5935439](https://steamdb.info/patchnotes/5935439/) | ClientVersion 4553 | [7.28 5984251](https://steamdb.info/patchnotes/5984251/) | 4553 | Added |
| 7.28 | 7.28c | [6503851](https://steamdb.info/patchnotes/6503851/) | ClientVersion 4788 | [7.29 6517216](https://steamdb.info/patchnotes/6517216/) | 4788 | Added |
| 7.29 | 7.29d | [7198695](https://steamdb.info/patchnotes/7198695/) | ClientVersion 4970 | [7.30 7206228](https://steamdb.info/patchnotes/7206228/) | 4970 | Added |
| 7.30 | 7.30e | [8248131](https://steamdb.info/patchnotes/8248131/) | ClientVersion 5175 | [7.31 8262549](https://steamdb.info/patchnotes/8262549/) | 5175 | Matched existing recipe |
| 7.31 | 7.31d | [9335939](https://steamdb.info/patchnotes/9335939/) | ClientVersion 5382 | [7.32 9374346](https://steamdb.info/patchnotes/9374346/) | 5382 | Matched existing recipe |
| 7.32 | 7.32e | [10978579](https://steamdb.info/patchnotes/10978579/) | — | [7.33 11054414](https://steamdb.info/patchnotes/11054414/) | 5677 | Matched existing recipe |
| 7.33 | 7.33e | [11887689](https://steamdb.info/patchnotes/11887689/) | — | [7.34 11896549](https://steamdb.info/patchnotes/11896549/) | 5771 | Added |
| 7.34 | 7.34e | [12894231](https://steamdb.info/patchnotes/12894231/) | — | [7.35 12966865](https://steamdb.info/patchnotes/12966865/) | 5938 | Added |
| 7.35 | 7.35d | [14448040](https://steamdb.info/patchnotes/14448040/) | — | [7.36 14461833](https://steamdb.info/patchnotes/14461833/) | 6061 | Added |
| 7.36 | 7.36c | [15192472](https://steamdb.info/patchnotes/15192472/) | — | [7.37 15219244](https://steamdb.info/patchnotes/15219244/) | 6134 | Added |
| 7.37 | 7.37e | [17314470](https://steamdb.info/patchnotes/17314470/) | — | [7.38 17415045](https://steamdb.info/patchnotes/17415045/) | 6312 | Added |
| 7.38 | 7.38c | [18497749](https://steamdb.info/patchnotes/18497749/) | — | [7.39 18572659](https://steamdb.info/patchnotes/18572659/) | 6408 | Added |
| 7.39 | 7.39e | [21169217](https://steamdb.info/patchnotes/21169217/) | The International 2026 Live Event Broadcast RFP and Broadcast License Requests | [7.40 21199935](https://steamdb.info/patchnotes/21199935/) | 6640 | Matched existing recipe |
| 7.40 | 7.40c | [22472058](https://steamdb.info/patchnotes/22472058/) | — | [7.41 22489178](https://steamdb.info/patchnotes/22489178/) | 6726 | Matched existing recipe |
| 7.41 | 7.41f | [26718111](https://steamdb.info/patchnotes/26718111/) | — | [7.42 26767486](https://steamdb.info/patchnotes/26767486/) | 6976 | Matched existing recipe |

## Release titles that needed corroboration

- **6.85**. Valve's 6.85 Steam update identifies the September 24 release near the 23:39 UTC build. [SteamDB build](https://steamdb.info/patchnotes/788939/) [Corroboration 1](https://store.steampowered.com/oldnews/18555)
- **6.86**. First public build on the Balance of Power release date. All eight depots changed. [SteamDB build](https://steamdb.info/patchnotes/902132/) [Corroboration 1](https://www.dota2.com/balanceofpower)
- **6.87**. First listed public build following Valve's 6.87 release announcement. [SteamDB build](https://steamdb.info/patchnotes/1094257/) [Corroboration 1](https://www.dota2.com/687)
- **6.88**. Valve's 6.88 Steam update precedes the 05:26 UTC build. [SteamDB build](https://steamdb.info/patchnotes/1177581/) [Corroboration 1](https://store.steampowered.com/oldnews/22385)
- **7.00**. Valve announced live 7.00 at 00:37 UTC, five minutes after this public build. [SteamDB build](https://steamdb.info/patchnotes/1514733/) [Corroboration 1](https://www.dota2.com/700/eng)
- **7.01**. The archived build changes Jingu Mastery's counter duration from 15 to 10, matching Valve's 7.01 notes. [SteamDB build](https://steamdb.info/patchnotes/1532815/) [Corroboration 1](https://store.steampowered.com/oldnews/26467) [Corroboration 2](https://github.com/SteamTracking/GameTracking-Dota2/commit/1a9f3fea592a9c7c8c78adbae07eafd1c191cae3)
- **7.02**. Valve's 7.02 announcement followed this public build by five minutes. [SteamDB build](https://steamdb.info/patchnotes/1619465/) [Corroboration 1](https://store.steampowered.com/oldnews/27381)
- **7.03**. First release-window build after the Bladeform Legacy announcement. [SteamDB build](https://steamdb.info/patchnotes/1693635/) [Corroboration 1](https://www.dota2.com/bladeformlegacy)
- **7.04**. The archived build contains the recipe changes for Hurricane Pike and Silver Edge in Valve's 7.04 notes. [SteamDB build](https://steamdb.info/patchnotes/1710820/) [Corroboration 1](https://store.steampowered.com/oldnews/28351) [Corroboration 2](https://github.com/SteamTracking/GameTracking-Dota2/commit/94d6bab6bcaee9beffa6b378c86088717296f964)
- **7.05**. First April 9 build. Archived gameplay changes and Valve's April 9 notes corroborate the window. [SteamDB build](https://steamdb.info/patchnotes/1744804/) [Corroboration 1](https://store.steampowered.com/oldnews/28757) [Corroboration 2](https://github.com/SteamTracking/GameTracking-Dota2/commit/2f48467c4e262f95faf9f7023575e952c5ac2d07)
- **7.06**. The archived build contains the 7.06 global strength gain and health regeneration changes. Build 1822758 is a follow-up. [SteamDB build](https://steamdb.info/patchnotes/1822478/) [Corroboration 1](https://github.com/SteamTracking/GameTracking-Dota2/commit/7e824535a2b6dbd0a4a2da64709090ac0fabc78e)
- **7.07**. Pangolier and Dark Willow appear in the archived snapshot and are absent in its parent. [SteamDB build](https://steamdb.info/patchnotes/2246740/) [Corroboration 1](https://www.dota2.com/duelingfates) [Corroboration 2](https://raw.githubusercontent.com/SteamTracking/GameTracking-Dota2/efc7bea3ec1c099c9c60bca99770eb2be525105b/game/dota/pak01_dir.txt)
- **7.14**. The patch body identifies 7.14 at build 2724014 despite the generic ClientVersion title and earlier calendar date. [SteamDB build](https://steamdb.info/patchnotes/2724014/) [Corroboration 1](https://store.steampowered.com/oldnews/39548)
- **7.18**. The archived gameplay diff for this build contains 7.18 balance changes. [SteamDB build](https://steamdb.info/patchnotes/2894132/) [Corroboration 1](https://www.dota2.com/patches/7.18)
- **7.19**. The patch body and archived gameplay diff identify 7.19. [SteamDB build](https://steamdb.info/patchnotes/2987543/) [Corroboration 1](https://www.dota2.com/patches/7.19)
- **7.20**. The build adds the 7.20 patch background and archives the 7.19 map. [SteamDB build](https://steamdb.info/patchnotes/3320919/) [Corroboration 1](https://www.dota2.com/720)
- **7.25**. The gameplay diff and localization identify 7.25. [SteamDB build](https://steamdb.info/patchnotes/4788262/) [Corroboration 1](https://www.dota2.com/patches/7.25)
- **7.27**. Changelist 8811505 shows 5226294 becoming public at 23:21:04 UTC on June 28. Its archived files add Blitz Knuckles and Voodoo Mask and reduce Quelling Blade to 130 gold, all matching the 7.27 notes. Prior build 5222216 has neither item and charges 150 gold for Quelling Blade. The later 7.27-titled build 5226375 restored earlier manifests. [Public rollout](https://steamdb.info/app/570/history/?changeid=8811505) [Manifest rollback](https://steamdb.info/app/570/history/?changeid=8811660) [7.26c item definitions](https://raw.githubusercontent.com/SteamTracking/GameTracking-Dota2/bb027f15b3bd67267ff59ff686edb707b861d56b/game/dota/pak01_dir/scripts/npc/items.txt) [7.27 item definitions](https://raw.githubusercontent.com/SteamTracking/GameTracking-Dota2/9637aafdbd8bc42cd6a92d6e0ed98ebf54906c4a/game/dota/pak01_dir/scripts/npc/items.txt) [Patch notes](https://steamdb.info/patchnotes/5226375/)
- **7.33**. New Frontiers is the 7.33 release. [SteamDB build](https://steamdb.info/patchnotes/11054414/) [Corroboration 1](https://www.dota2.com/newfrontiers)
- **7.35**. Frostivus 2023 is the 7.35 release. [SteamDB build](https://steamdb.info/patchnotes/12966865/) [Corroboration 1](https://www.dota2.com/frostivus2023)
- **7.39**. Dota Springs Forward is the 7.39 release. [SteamDB build](https://steamdb.info/patchnotes/18572659/) [Corroboration 1](https://www.dota2.com/patches/7.39)
- **7.41**. This is the earlier of two 7.41-titled builds. The second appears a day later. [SteamDB build](https://steamdb.info/patchnotes/22489178/)
- **7.42**. The named build matches Valve's 7.42 announcement. [SteamDB build](https://steamdb.info/patchnotes/26767486/) [Corroboration 1](https://www.dota2.com/newsentry/689773669992367212)
