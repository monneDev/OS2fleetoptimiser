import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import extract, func, literal_column, text
from sqlalchemy.orm.query import Query
from sqlalchemy.engine.base import Engine

from fleetmanager.data_access.db_engine import engine_creator
from fleetmanager.data_access.dbschema import RoundTrips, RoundTripSegments


def generate_trips_simulation(
    pool_id: int,
    seed: int = None,
    padding: float = 1.2,
    dates: list = [],
    vehicles: list = [],
    engine: Engine = None,
):
    """
    Generates two list of possible trips for specific pool

    Parameters
    ----------
    dates : list
        The selected start - and end date of simulation period
    pool_id : int
        The pool to simulate.
    seed : int
        The seed of the random function that samples trips.
    padding : float
        increases the amount of simulated trips by a percentage

    Returns
    -------
    simulated_day: list[Dict]
        A list of trips from an average simulated day.
    peak_day: list[Dict]
        The list of trips from the day with most trips.
    """
    if len(dates) == 0:
        dates = [datetime(year=2022, month=1, day=20), datetime.now()]
    if engine is None:
        engine = engine_creator()
    data = pd.read_sql(
        Query([RoundTrips.start_time, RoundTrips.end_time, RoundTrips.distance])
        .filter(
            RoundTrips.start_location_id == pool_id,
            RoundTrips.start_time >= dates[0],
            RoundTrips.end_time <= dates[-1],
            RoundTrips.car_id.in_(vehicles),
        )
        .statement,
        engine,
        parse_dates={
            "start_time": {"format": "%Y/%m/%d"},
            "end_time": {"format": "%Y/%m/%d"},
        },
    )

    # Remove trips spanning multiple days
    mask = data.apply(lambda row: row["end_time"].day == row["start_time"].day, axis=1)
    data = data[mask]

    if data.size == 0:
        return [], []
    else:
        return (
            __simulate_avg_day(data, seed=seed, padding=padding),
            extract_peak_day(data),
        )


def __minutes_since_midnight(timestamp):
    midnight = timestamp.replace(hour=0, minute=0, second=0)
    return (timestamp - midnight).seconds / 60


def extract_peak_day(data):
    # Expand the trips using the roundtripsegments to get exact distances
    expanded_rows = []
    for row in data.itertuples():
        roundtripsegments = (
            [row._asdict()]
            if hasattr(row, "trip_segments") is False
            or len(getattr(row, "trip_segments")) == 0
            else row.trip_segments
        )
        for segment in roundtripsegments:
            start_time = pd.to_datetime(segment["start_time"])
            end_time = pd.to_datetime(segment["end_time"])
            distance = segment["distance"]

            # Handle the cases where segments span multiple days
            num_days = (end_time.date() - start_time.date()).days + 1
            daily_distance = distance / num_days

            for offset in range(num_days):
                day = start_time.date() + pd.Timedelta(days=offset)
                expanded_rows.append({"date": day, "distance": daily_distance})

    expanded_data = pd.DataFrame(expanded_rows)
    daily_totals = expanded_data[["distance", "date"]].groupby("date").sum()

    peak_day_date = daily_totals["distance"].idxmax()
    peak_day_datetime_start = datetime.combine(peak_day_date, time(0, 0, 0))
    peak_day_datetime_end = peak_day_datetime_start + timedelta(hours=23, minutes=59, seconds=59)

    day_mask = data["start_time"].dt.date <= peak_day_date
    day_mask &= data["end_time"].dt.date >= peak_day_date

    peak_day_trips = data[day_mask]

    # Extract the roundtripsegments and create fictive ones if they span multiple days
    peak_day = []
    for row in peak_day_trips.itertuples():
        trip = {"distance": 0, "trip_segments": []}
        if hasattr(row, "trip_segments"):
            removed_segments = []
            for segment in row.trip_segments:
                # only use the row.trip_segments that actually take place on the peak day
                # if the segment spans across midnight or multiple days - make a segment that covers the relative
                # distance
                start_time_segment = segment["start_time"]
                end_time_segment = segment["end_time"]
                if start_time_segment.date() != peak_day_date and end_time_segment.date() != peak_day_date:
                    removed_segments.append(segment)
                    continue

                distance_segment = segment["distance"]

                if start_time_segment.date() != peak_day_date or end_time_segment.date() != peak_day_date:
                    fix_start = start_time_segment.date() != peak_day_date
                    time_overdue = (peak_day_datetime_start - start_time_segment if fix_start else end_time_segment - peak_day_datetime_end).total_seconds()
                    relative_time_spent = time_overdue / (end_time_segment - start_time_segment).total_seconds()
                    distance_segment = distance_segment - (relative_time_spent * distance_segment)
                    start_time_segment = peak_day_datetime_start if fix_start else start_time_segment
                    end_time_segment = peak_day_datetime_end if not fix_start else end_time_segment

                trip["distance"] += distance_segment
                trip["trip_segments"].append(
                    {
                        "start_time": start_time_segment,
                        "end_time": end_time_segment,
                        "distance": distance_segment
                    }
                )

        trip["start_time"] = (
            row.start_time.to_pydatetime()
            if trip["distance"] == 0 or not hasattr(row, "trip_segments")
            else trip["trip_segments"][0]["start_time"]
        )
        trip["end_time"] = (
            row.end_time.to_pydatetime()
            if trip["distance"] == 0 or not hasattr(row, "trip_segments")
            else trip["trip_segments"][-1]["end_time"]
        )
        trip["distance"] = row.distance if trip["distance"] == 0 else trip["distance"]

        total_trip_time = None

        if trip["start_time"].date() != peak_day_date:
            total_trip_time = (trip["end_time"] - trip["start_time"]).total_seconds()
            time_overdue = (peak_day_datetime_start - trip["start_time"]).total_seconds()
            relative_time_spent = time_overdue / total_trip_time
            trip["start_time"] = peak_day_datetime_start
            trip["distance"] = trip["distance"] - (relative_time_spent * trip["distance"])

        if trip["end_time"].date() != peak_day_date:
            if total_trip_time is None:
                total_trip_time = (trip["end_time"] - trip["start_time"]).total_seconds()
            time_overdue = (trip["end_time"] - peak_day_datetime_end).total_seconds()
            relative_time_spent = time_overdue / total_trip_time
            trip["end_time"] = peak_day_datetime_end
            trip["distance"] = trip["distance"] - (relative_time_spent * trip["distance"])

        peak_day.append(trip)

    return pd.DataFrame(peak_day)


def __simulate_avg_day(data, seed, padding):
    grouped_start_time = data.groupby([data["start_time"].dt.date])
    # Add 20% to compensate for missing trips in database
    avg_trips_pr_day = round(grouped_start_time.size().mean() * padding)

    km_pr_min = data.apply(
        lambda row: (((row["end_time"] - row["start_time"]).seconds / 60))
        / row["distance"],
        axis=1,
    ).mean()

    distances = data["distance"].tolist()
    start_times = data["start_time"].apply(
        lambda x: __minutes_since_midnight(x.to_pydatetime())
    )

    # Histogram bins: 1 bin pr 10 km and 1 bin pr. 15 min
    distance_bins = round((round(data["distance"].max() - data["distance"].min())) / 10)
    start_time_bins = round((start_times.max() - start_times.min()) / 15)
    if distance_bins == 0:
        simulated_day = []
        for k, trip in enumerate(data.itertuples()):
            simulated_day.append(
                {
                    "id": k,
                    "start_time": trip.start_time,
                    "end_time": trip.end_time,
                    "length_in_kilometers": trip.distance,
                }
            )
        return simulated_day

    (
        hist,
        x_bins,
        y_bins,
    ) = np.histogram2d(distances, start_times, bins=(distance_bins, start_time_bins))
    x_bin_midpoints = (x_bins[:-1] + x_bins[1:]) / 2
    y_bin_midpoints = (y_bins[:-1] + y_bins[1:]) / 2

    cdf = np.cumsum(hist.flatten())
    cdf = cdf / cdf[-1]

    if seed != None:
        np.random.seed(seed)

    values = np.random.rand(avg_trips_pr_day)
    value_bins = np.searchsorted(cdf, values)

    x_idx, y_idx = np.unravel_index(
        value_bins, (len(x_bin_midpoints), len(y_bin_midpoints))
    )
    random_from_cdf = np.column_stack((x_bin_midpoints[x_idx], y_bin_midpoints[y_idx]))
    new_distances, new_start_times = random_from_cdf.T

    simulated_day = []

    for i in range(avg_trips_pr_day):
        start_time = datetime.now() + timedelta(days=365, minutes=new_start_times[i])
        end_time = start_time + timedelta(minutes=new_distances[i] * km_pr_min)
        simulated_day.append(
            {
                "id": i,
                "start_time": start_time,
                "end_time": end_time,
                "length_in_kilometers": new_distances[i],
            }
        )

    return simulated_day


def shiftify(roundtrips, shifts):
    def create_aggregate(routes):
        use_trip_segment = True if "trip_segments" in routes[0]._asdict() else False
        aggregated_routes = {
            "id": routes[0].id,
            "start_time": routes[0].start_time,
            "end_time": routes[-1].end_time,
            "length": len(routes),
            "car_id": routes[0].car_id,
            "belongs_tos": [a.belongs_to for a in routes][0],
            "distance": sum([a.distance for a in routes]),
            "start_latitude": routes[0].start_latitude,
            "start_longitude": routes[0].start_longitude,
            "end_latitude": routes[0].end_latitude,
            "end_longitude": routes[0].end_longitude,
            "start_location_id": routes[0].start_location_id,
            "aggregation_type": None
            if "aggregation_type" not in routes[0]._asdict()
            else (
                "complete"
                if any(
                    [
                        pd.isna(typ.aggregation_type) is False
                        and "complete" in typ.aggregation_type
                        for typ in routes
                    ]
                )
                else routes[0].aggregation_type
            ),
            "address": getattr(routes[0], "address", None),
            "trip_segments": [
                segment for trip in routes for segment in trip.trip_segments
            ]
            if use_trip_segment
            else [],
            "plate": getattr(routes[0], "plate", None),
            "make": getattr(routes[0], "make", None),
            "model": getattr(routes[0], "model", None),
            "department": getattr(routes[0], "department", None),
        }
        return aggregated_routes

    def within_breaktime(break_period, end_time):
        if break_period is None:
            return False
        start_break, end_break = break_period
        if start_break < end_break:
            return start_break <= end_time <= end_break
        else:
            return end_time >= start_break or end_time <= end_break

    midnight = time(hour=0)

    shifts = [
        {
            "shift_start": a["shift_start"],
            "shift_end": a["shift_end"],
            "overnight": True
            if a["shift_end"] < a["shift_start"] and a["shift_end"] != midnight
            else False,
            "break": a["break"],
        }
        for a in shifts
    ]

    half_an_our = timedelta(seconds=60 * 30)

    breaks = {
        str(k): a["break"]
        if pd.isna(a["break"])
        else (
            (datetime.combine(date(1, 1, 1), a["break"]) - half_an_our).time(),
            (datetime.combine(date(1, 1, 1), a["break"]) + half_an_our).time(),
        )
        for k, a in enumerate(shifts)
    }
    max_shift = max(
        [
            datetime.combine(date(1, 1, 1), a["shift_end"])
            - datetime.combine(date(1, 1, 1), a["shift_start"])
            for a in shifts
        ]
        + [timedelta(hours=24) / len(shifts)]
    )

    overnight_shift = [str(k) for k, a in enumerate(shifts) if a["overnight"]] + [None]
    overnight_shift = overnight_shift[0]
    multi_days = timedelta(days=1)
    new_trips = pd.DataFrame()
    # for each unique car
    for car in roundtrips.car_id.unique():
        # sort by trip start time and copy
        c_trips = (
            roundtrips[roundtrips.car_id == car].sort_values(["start_time"]).copy()
        )
        if car is None:
            c_trips = (
                roundtrips[roundtrips.car_id.isna()].sort_values(["start_time"]).copy()
            )
        # if the car has no associated trips do nothing
        if len(c_trips) == 0:
            continue
        for k, shift in enumerate(shifts):
            c_trips[str(k)] = c_trips.apply(
                alternate, ssh=shift["shift_start"], seh=shift["shift_end"], axis=1
            )
        c_trips["belongs_to"] = c_trips.iloc[:, -len(shifts) :].idxmax(axis=1)
        c_trips["duration"] = c_trips.end_time - c_trips.start_time

        prev = None
        prev_date = None
        agg_trip = []
        c_rt = []
        for trip in c_trips.itertuples():
            if car is None or trip.duration > timedelta(hours=24):
                agg_trip.append(create_aggregate([trip]))
                continue

            if prev is None:
                prev = trip.belongs_to
                prev_date = trip.start_time

            was_a_break = False

            allowed_break = breaks[trip.belongs_to]
            # todo what to do with the none car_id?
            if (
                (prev != trip.belongs_to)
                or (
                    prev_date.date() != trip.start_time.date()
                    and trip.belongs_to != overnight_shift
                )
                or (
                    len(c_rt) > 0 and trip.start_time - c_rt[-1].start_time >= max_shift
                )
                or (trip.end_time - trip.start_time >= multi_days)
                or (within_breaktime(allowed_break, trip.end_time.time()))
            ):
                if within_breaktime(allowed_break, trip.end_time.time()):
                    was_a_break = True

                    if (
                        prev == trip.belongs_to
                    ):  # the previous was the same so they belong
                        if (
                            len(c_rt) > 0
                            and trip.start_time - c_rt[-1].start_time >= max_shift
                        ) or (
                            prev_date.date() != trip.start_time.date()
                            and trip.belongs_to != overnight_shift
                        ):
                            agg_trip.append(create_aggregate(c_rt))
                            agg_trip.append(create_aggregate([trip]))
                        else:
                            c_rt.append(trip)
                            agg_trip.append(create_aggregate(c_rt))

                    else:  # separate shifts
                        agg_trip.append(create_aggregate(c_rt))
                        agg_trip.append(create_aggregate([trip]))

                else:
                    agg_trip.append(create_aggregate(c_rt))

                prev = None
                prev_date = None
                c_rt = []

            if was_a_break is False:
                c_rt.append(trip)
                prev = trip.belongs_to
                prev_date = trip.start_time

        if c_rt:
            agg_trip.append(create_aggregate(c_rt))

        new_trips = pd.concat(
            [new_trips, pd.DataFrame(agg_trip)]
        )  # new_trips.append(agg_trip, ignore_index=True)

    return new_trips


def alternate(row, ssh=time(hour=7), seh=time(hour=15)):
    """
    return the time spent in a given time range. ssh = start time of shift, seh end time of the shift
    handles across midnight trips as well as across midnight shifts.
    """
    if type(row) is dict:
        start_time = row["start_time"]
        start_time_time = start_time.time()
        end_time = row["end_time"]
        end_time_time = end_time.time()
    else:
        start_time = row.start_time
        start_time_time = start_time.time()
        end_time = row.end_time
        end_time_time = end_time.time()

    ss = ssh
    se = seh

    day_one = date(year=1, month=1, day=1)
    day_two = date(year=1, month=1, day=2)

    time = timedelta(0)
    zero = timedelta(0)
    aday = timedelta(days=1)
    if start_time_time > end_time_time:
        # the route runs over midnigt
        if ss > se:
            # the shift runs over midnight
            if start_time_time <= ss and end_time_time >= se:
                # the route starts before the shift and ends after the shift end
                time = datetime.combine(day_two, se) - datetime.combine(day_one, ss)
            elif start_time_time <= ss and end_time_time <= se:
                time = datetime.combine(day_two, end_time_time) - datetime.combine(day_one, ss)
                # the route starts before the shift and ends before the shift end
            elif start_time_time >= ss and end_time_time <= se:
                time = end_time - start_time
                # the route starts after the shift and ends before the shift end
            elif start_time_time >= ss and end_time_time >= se:
                time = datetime.combine(end_time.date(), se) - start_time
                # the route starts after the shift and ends after the shift end
        else:
            # the shift doesn't run over midnight
            tran_s = datetime.combine(day_one, start_time_time)
            tran_e = datetime.combine(day_two, end_time_time)
            alt_ss = datetime.combine(day_one, ss)
            alt_es = datetime.combine(day_one, se)

            if alt_es < tran_s:
                alt_es += aday
                alt_ss += aday
            if tran_s >= alt_ss and tran_e >= alt_es:
                time = alt_es - tran_s
                # the route starts after the shift and ends after the shift end
            elif tran_s >= alt_ss and tran_e <= alt_es:
                time = tran_e - tran_s
                # the route starts after the shift and ends before the shift end
            elif tran_s <= alt_ss and tran_e <= alt_es:
                time = tran_e - alt_ss
                # the route starts before the shift and ends before the shift end
            elif tran_s <= alt_ss and tran_e >= alt_es:
                time = alt_es - alt_ss
                # the route starts before the shift and ends after the shift end
    else:
        # the route doesn't run over midnight
        if ss > se:
            # the shift runs over midnight
            alt_ss = datetime.combine(day_one, ss)
            alt_es = datetime.combine(day_two, se)
            tran_s = datetime.combine(day_one, start_time_time)
            tran_e = datetime.combine(day_one, end_time_time)

            if tran_e < alt_ss:
                tran_s += aday
                tran_e += aday

            if tran_s <= alt_ss and tran_e <= alt_es:
                time = tran_e - alt_ss
                # the route starts before the shift and ends before the shift end
            elif tran_s <= alt_ss and tran_e >= alt_es:
                # the route starts before the shift and ends after the shift end
                time = alt_es - alt_ss
            elif tran_s >= alt_ss and tran_e >= alt_es:
                # the route starts after the shift and ends after the shift end
                time = alt_es - tran_s
            elif tran_s >= alt_ss and tran_e <= alt_es:
                time = tran_e - tran_s
                # the route starts after the shift and ends before the shift end
        else:
            start = datetime.combine(day_one, start_time_time)
            end = datetime.combine(day_one, end_time_time)
            ss = datetime.combine(day_one, ss)
            se = datetime.combine(day_one, se)
            # the shift doesn't run over midnight
            if start >= ss and end <= se:
                # the route starts after the shift and ends before the shift end
                time = end - start
            elif start >= ss and end >= se:
                # the route starts after the shift and ends after the shift end
                time = se - start
            elif start <= ss and end >= se:
                # the route starts before the shift and ends after the shift end
                time = se - ss
            elif start <= ss and end <= se:
                # the route starts before the shift and ends before the shift end
                time = end - ss
    if time < zero:
        time = zero
    return time.total_seconds()


def get_kilometer_per_hour(roundtrip_frame, engine):
    batch_size = 2000

    round_trip_ids = roundtrip_frame.id.values.tolist()
    batches = [round_trip_ids[i:i + batch_size] for i in range(0, len(round_trip_ids), batch_size)]
    aggregated_frame = pd.DataFrame()

    for batch in batches:
        query = create_query(batch, engine)
        frame = pd.read_sql(query.statement, engine)
        frame = calculate_km_per_hour(frame)
        aggregated_frame = pd.concat([aggregated_frame, frame], ignore_index=True)

    roundtrip_frame = merge_results(roundtrip_frame, aggregated_frame)

    return roundtrip_frame


def create_query(batch, engine):
    if engine.dialect.name == "sqlite":
        time_difference = func.strftime("%s", RoundTripSegments.end_time) - func.strftime("%s", RoundTripSegments.start_time)
    elif engine.dialect.name == "mysql":
        time_difference = func.timestampdiff(text("SECOND"), RoundTripSegments.start_time, RoundTripSegments.end_time)
    elif engine.dialect.name == "postgresql":
        time_difference = extract(
            "epoch", RoundTripSegments.end_time - RoundTripSegments.start_time
        )
    else:
        time_difference = func.datediff(literal_column("SECOND"), RoundTripSegments.start_time, RoundTripSegments.end_time)

    query = (
        Query(
            [
                RoundTripSegments.round_trip_id,
                (func.sum(time_difference) / 3600).label("hours_effective_driving"),
                func.min(RoundTripSegments.start_time),
                func.max(RoundTripSegments.end_time),
                func.sum(RoundTripSegments.distance).label("distance"),
            ]
        )
        .filter(RoundTripSegments.round_trip_id.in_(batch))
        .group_by(RoundTripSegments.round_trip_id)
    )
    return query


def calculate_km_per_hour(frame):
    frame["km/h"] = frame.apply(
        lambda row: 0 if row["hours_effective_driving"] == 0 else row["distance"] / row["hours_effective_driving"],
        axis=1
    )
    return frame


def merge_results(roundtrip_frame, aggregated_frame):
    roundtrip_frame = roundtrip_frame.merge(
        aggregated_frame, left_on="id", right_on="round_trip_id", how="left"
    )

    roundtrip_frame["km/h"] = roundtrip_frame.apply(
        lambda row: row["km/h"] if pd.notna(row["km/h"]) else row.distance_x / ((row["end_time"] - row["start_time"]).total_seconds() / 3600),
        axis=1
    )

    roundtrip_frame.drop(
        ["min_1", "max_1", "distance_y", "hours_effective_driving", "round_trip_id"],
        axis=1, inplace=True
    )
    roundtrip_frame.rename({"distance_x": "distance"}, axis=1, inplace=True)

    return roundtrip_frame
