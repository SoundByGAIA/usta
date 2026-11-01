def parse_args(argv):
    out = {"verbose": False, "name": None, "count": 1, "files": []}
    i = 0
    args = list(argv)

    def value(opt, inline):
        nonlocal i
        if inline is not None:
            return inline
        i += 1
        if i >= len(args):
            raise ValueError(f"{opt} için değer eksik")
        return args[i]

    while i < len(args):
        a = args[i]
        if a == "--":
            out["files"].extend(args[i + 1 :])
            break
        if a == "-" or not a.startswith("-"):
            out["files"].append(a)
        else:
            opt, eq, inline = a.partition("=")
            inline = inline if eq else None
            if opt in ("-v", "--verbose"):
                if inline is not None:
                    raise ValueError("--verbose değer almaz")
                out["verbose"] = True
            elif opt in ("-n", "--name"):
                out["name"] = value(opt, inline)
            elif opt == "--count":
                try:
                    out["count"] = int(value(opt, inline))
                except ValueError:
                    raise ValueError("count tamsayı olmalı") from None
            else:
                raise ValueError(f"bilinmeyen seçenek: {opt}")
        i += 1
    return out
