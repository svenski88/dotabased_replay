# Replay library guide

[Back to DotaBased Replay](../README.md)

## Browse, search, and annotate

**Rescan library** discovers new and changed replay files. An unavailable folder keeps its previous catalog until it becomes accessible. Open **Scan details** for missing folders, unreadable summaries, and other scan errors.

Search requires every term to match the same game. Separate terms with spaces or commas and put phrases in double quotes. Search covers recorded player names and IDs, local nicknames, hero names and aliases, replay paths, metadata, notes, and parsed chat. Short terms such as `AM` match whole words, ambiguous aliases such as `ES` can match either hero, and the word `and` is treated as text.

Click column headings to sort. Ctrl-click toggles rows, Shift-click selects a range, and Ctrl+A selects all visible rows. **Copy** chooses a physical replay for viewing, while **Size total** counts all copies. **Copy Match ID** is available when the selected match has a known ID.

Edit **Match notes** or assign a rating from one to five stars. Click the same star to clear it, or press `0`–`5` while the grid has focus. Notes, ratings, and client overrides are tied to the match and survive removal of replay copies. **Import notes…** reads annotated Dotabuff or OpenDota links from local text and Markdown, preserves existing notes, and backs up the database.

**Frequent players > 5%** counts unique matches to find players worth pinning. Nicknames are local. Account checkboxes control participation in **Only games with enabled accounts**. The **Pinned Players** column still shows tracked players present in the match. Enable **League games** to filter by recorded or enriched league IDs. **Hide unknown recordings** is enabled by default.

## Parse replays and fill metadata gaps

Run **Parse All** for the full catalog, including hidden unknown recordings, or **Parse Selected** to process a subset. Full parsing refreshes the catalog first and caches successful results by file size, modification time, and parser version. **Stop Parsing** retains completed results. Browsing stays available while parsing runs. **Parse details** shows progress, field sources, and errors for individual copies.

Open **Chat Log** after a successful Source 2 parse to see recorded messages with their speaker, channel, and game clock when available. Some replays omit team or private chat, and unsupported or incomplete recordings may have no log. Run **Parse Selected** again to add chat or graph data missing from older caches.

Verified replay metadata takes priority over OpenDota. Use **Fetch selected metadata** for one known match or **Enrich next 20** for up to 20 visible uncached matches. **Stop network batch** stops after the current request. Use the account lookup for optional public profile metadata. By default the app spaces OpenDota requests at least 2.1 seconds apart, caps them at 1,000 per UTC day, and pauses on rate limits. Successful match and profile lookups are cached for 365 and seven days respectively. Expired data stays visible offline.

## Read graphs and categories

Gold and XP show the Radiant-minus-Dire advantage. Hover for the raw difference, the share of combined team resources, and its 30-second median. Legend checkboxes toggle individual lines. Kills appear above or below the plot by credited team, and towers, barracks, and Roshan have separate markers. The **Players & Accounts** and **Chat Log** panels expand and resize independently.

Right-click a graph time to copy a `demo_gototick` console command. The command uses the nearest saved replay packet tick, including timing offsets. Parse an older cached replay again if its graph lacks tick mappings.

The local **micro19** model estimates win probability for league and non-league games. It needs player net worth and building state. Older recordings can still show XP and events when net worth or a win estimate is unavailable. See the [model notes](../models/README.md) for the training artifact's limitations.

Categories use a trailing 30-second median and at least 95% resource coverage, with gold preferred and XP used when direct net worth is unavailable. Hover over the graph readout to see the resource basis and qualifying interval. The classifier uses resource advantages independently of the win estimate.

| Category | Rule |
| --- | --- |
| **Comeback** | The eventual winner trails by at least 10% of combined resources for at least two minutes after minute five. This takes priority over the other categories. |
| **Stomp** | The winner sustains a 7.5% lead for two minutes by minute 10 and maintains dominance afterward, allowing brief dips. |
| **Close Game** | At least 60% of the window from five minutes before the finish to one minute before it stays within ±5%. |
| **Other** | Sufficient data without a qualifying pattern. |
| **Insufficient data / Not parsed** | The evidence is unavailable, or graph data has yet to be extracted. |

## Move and delete recordings

1. Open **Libraries & clients → Migration rules…**. Choose a client, a registered source library, and an existing non-overlapping destination folder.
2. Set **Modified before (YYYY-MM-DD)**. It compares replay file modification time strictly before local midnight. To move a whole library, choose a later date than all its file modification times.
3. Save the rule and use **Preview migrations** to inspect paths and sizes. **Confirm move of previewed files** starts the move. **Stop after current file** finishes the active copy before stopping.

Moves preserve subfolders, verify copied bytes before removing originals, and work across drives. Existing destination files, changed replay files, and symlinks or junctions are refused. The destination is registered as a library for the same client. If copying is interrupted, the original remains and an incomplete destination may need review before trying again. A rescan discovers both copies when a verified copy is retained after a partial failure.

For a manual move, preserve file modification timestamps, register the new folder, and rescan. Compatible caches can follow when file size, exact modification time, and match identity still agree. Where recovery is unavailable or caches conflict, parse again. Match notes and ratings are tied to the match ID.

**Remove library** only removes catalog entries. **Delete selected files…** lists physical copies for confirmation and lets you uncheck copies to keep. Confirmed deletion bypasses the Recycle Bin.
