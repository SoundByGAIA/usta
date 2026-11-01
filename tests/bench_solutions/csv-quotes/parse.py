import csv


def parse_line(line):
    rows = list(csv.reader([line]))
    return (rows[0] if rows else []) or [""]
