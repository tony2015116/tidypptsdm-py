# Reference results of the R package, compared in tests/test_parity.py.
# Run from the repository root after installing tidypptsdm (R):
#   Rscript tests/make_fixtures.R
library(tidypptsdm)
library(data.table)
fx <- "tests/fixtures"
dir.create(fx, showWarnings = FALSE)

for (st in c("nedap", "fire")) {
  raw <- if (st == "nedap") tidypptsda::nedap else tidypptsda::fire
  v <- prep_visits(raw, verbose = 0)
  out <- v[, .(responder, identified, location, date,
               entry_time = format(entry_time, "%Y-%m-%d %H:%M:%S"),
               exit_time = format(exit_time, "%Y-%m-%d %H:%M:%S"),
               duration, feed_intake, weight)]
  fwrite(out, file.path(fx, paste0(st, "_visits.csv.gz")))
  for (cfg in list(list(tag = "d7", days = 7, end = NULL),
                   list(tag = "d21", days = 21, end = max(v$date) - 10))) {
    mon <- run_monitor(v, days = cfg$days, end_date = cfg$end, verbose = 0)
    for (tb in c("stations", "houses", "pigs", "pig_summary", "hours", "alerts")) {
      fwrite(mon[[tb]], file.path(fx, sprintf("%s_%s_%s.csv", st, cfg$tag, tb)))
    }
  }
}

# a station without visits on the last day and a pig that stops visiting
v <- prep_visits(tidypptsda::nedap, verbose = 0)
end <- max(v$date)
pig <- v[location == "101" & identified, responder[3]]
sp <- v[!(location == "102" & date == end) & !(responder %in% pig & date >= end - 1)]
mon <- run_monitor(sp, days = 7, verbose = 0)
fwrite(mon$alerts, file.path(fx, "spoiled_alerts.csv"))
fwrite(mon$stations, file.path(fx, "spoiled_stations.csv"))
writeLines(pig, file.path(fx, "spoiled_pig.txt"))

w <- run_monitor(tidypptsda::nedap, days = 7, verbose = 0)
fwrite(wide_table(w$stations, "feed_kg"), file.path(fx, "nedap_d7_wide_feed.csv"))
fwrite(wide_table(w$pigs, "feed_kg"), file.path(fx, "nedap_d7_wide_pigfeed.csv"))
