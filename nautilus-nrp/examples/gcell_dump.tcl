# Dump the routing congestion that global routing saved in an ODB: per GCell, the maximum over routing layers of
# usage / capacity from the block's dbGCellGrid (no re-routing). Then summarize with scripts/gcell_stats.py.
#
#   GCELL_ODB=results/.../5_1_grt.odb GCELL_DUMP=grid.cong openroad -no_init -exit gcell_dump.tcl
#
# Output lines: "GRID nx ny", "GEXT x0 y0 x1 y1" (um), one "R v v v ..." line per GCell row (bottom row first,
# 3 decimals; capacity 0 with usage > 0 is written as 1.5), then "MACRO x0 y0 x1 y1" for every block instance.
# GEXT is the first and last GCell ORIGIN (getGridX/getGridY list origins), not the die outline: the pitch is
# (x1 - x0) / (nx - 1) and the last GCell runs on to the die edge (gcd: origins 0..31.35 um, die 36.725 um).
# Same algorithm as the Vastu ORFS checkout's vastu_setup/experiments/v060_comparison/congestion_heatmap.py.
#
# Caveats measured in 2026-10 (nangate45, ORFS default GRT):
#  * The saved grid stores macro-blocked tracks as USAGE (a fakeram GCell read metal2 15/15, metal3 20/20, metal4
#    10/10), so every GCell touching a macro reads exactly 1.0 here. Exclude macro GCells before computing p95,
#    mean or near-capacity shares; ">1.0" (overflow) is unaffected.
#  * Later stages can carry the grid: a flow that deletes 5_1_grt.odb after detailed route still has it in
#    6_final.odb. Record which checkpoint you read.
#  * Size memory from the ODB file, not the GCell count: peak RSS was 1.6-3.8x the ODB size (median 2.6) over 1,149
#    5_1_grt dumps and 2.8-3.7x (median 3.2) over 42 6_final dumps. Time was a median 34 s per million GCells, e.g.
#    70 s / 0.9 GB for 3.0M GCells and 2-5 min / 7.2-7.9 GB for a 2.5M-instance design's 4-8M GCells.
set odb $::env(GCELL_ODB)
set dump $::env(GCELL_DUMP)
read_db $odb
set block [ord::get_db_block]
set gcg [$block getGCellGrid]
if {$gcg eq "NULL" || $gcg eq ""} { puts stderr "no GCell grid in $odb"; exit 2 }
set fh [open $dump w]
set xg [$gcg getGridX]; set yg [$gcg getGridY]
set nx [llength $xg]; set ny [llength $yg]
puts $fh "GRID $nx $ny"
puts $fh "GEXT [ord::dbu_to_microns [lindex $xg 0]] [ord::dbu_to_microns [lindex $yg 0]] [ord::dbu_to_microns [lindex $xg end]] [ord::dbu_to_microns [lindex $yg end]]"
set rlayers {}
foreach lyr [[$block getTech] getLayers] {
  if {[$lyr getType] eq "ROUTING"} { lappend rlayers $lyr }
}
for {set j 0} {$j < $ny} {incr j} {
  set row {}
  for {set i 0} {$i < $nx} {incr i} {
    set best 0.0
    foreach lyr $rlayers {
      set u [$gcg getUsage $lyr $i $j]
      set c [$gcg getCapacity $lyr $i $j]
      if {$c > 0} { set r [expr {double($u) / $c}] } elseif {$u > 0} { set r 1.5 } else { set r 0.0 }
      if {$r > $best} { set best $r }
    }
    lappend row [format %.3f $best]
  }
  puts $fh "R $row"
}
foreach inst [$block getInsts] {
  if {[[$inst getMaster] isBlock]} {
    set bb [$inst getBBox]
    puts $fh "MACRO [ord::dbu_to_microns [$bb xMin]] [ord::dbu_to_microns [$bb yMin]] [ord::dbu_to_microns [$bb xMax]] [ord::dbu_to_microns [$bb yMax]]"
  }
}
close $fh
