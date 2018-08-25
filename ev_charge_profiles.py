# create numpy matrices with one row for each vehicle or homogeneous class
# matrices show availability (yes/no) in each hour,
# one row per vehicle, one column per hour of day
# sort hour indexes by unavailability of vehicle, price, time of day
# set first floor(charge req/charge rate) indices to charge rate
# set next index to remainder(charge req/charge rate)

# create flat file with vehicle id, hour within window, num hours needed,
# availability, rate (maybe), price (repeat hourly vector enough times) create
# new frame sorted by vehicle, availability, price, hour number; assign priority
# for each hour for each vehicle (1-24)
# use cumulative sum and compare to that, so we can handle different charging
# rates in different hours (e.g. 30 min availability at start)

# double up the work-chargeable private vehicles, with fractional weights for
# work charging and home charging (adjust weights to get desired share of overall
# driving)

# is_work_chargeable


# assign min( charging in all hours with
# priority <= num_needed; assign partial charging in all hours with priority ==
# floor(num_needed)

split flexible groups below into day/night charging windows, then re-aggregate to get day/night charging requirements (when setting up flexible charging)
70% of home-chargeable vehicles	home-charging gasoline vehicles	charge during home dwell time
50% of personal vehicles above 1 per apartment	home garage charging gasoline vehicles	charge during home dwell time
50% of non-home-chargeable personal vehicles (above 2 per detached home or 1 per apartment)	curb-charging gasoline vehicles	charge during home dwell time
all other personal vehicles	work-charging gasoline vehicles	charge during work dwell time
all gasoline vehicles minus personal vehicles	company-owned gasoline vehicles	charge at night
	non-bus diesel vehicles	charge at night
50% of bus fleet	on-route city buses	charge as baseload during day
50% of bus fleet	overnight-charging city buses	charge at night
