def month_report(model, output):
    print(f"{model.canonical_month_label} {model.year}")
    print(f"  media examined:       {model.total_media_examined}")
    print(f"  logical photo events: {model.logical_event_count}")
    print(f"  geotagged events:     {len(model.geo_events)}")
    print(f"  days with GPS:        {len(model.day_groups)}")
    print(f"  place clusters:       {len(model.clusters)}")
    print(f"  warnings:             {len(model.warnings)}")
    print(f"Created: {output}")


def year_report(model, output):
    print(str(model.year))
    print(f"  months with photos:   {len(model.months)}")
    print(f"  months with GPS:      {sum(m.geo_event_count > 0 for m in model.months)}")
    print(f"  annual map created:   yes")
    print(f"Created: {output}")
