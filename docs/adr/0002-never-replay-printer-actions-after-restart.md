# Never replay Printer actions after restart

Persist Action-request history across server restarts, but never automatically replay an accepted Printer action. Any request interrupted before Action confirmation becomes an Indeterminate action because repeating movement, heating, or print control after certainty is lost can duplicate a physical effect.
