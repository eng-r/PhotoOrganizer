MONTH_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}
MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December",
}

PREVIEWABLE_EXTENSIONS = {".jpg", ".jpeg"}
RAW_EXTENSIONS = {".cr2", ".cr3", ".arw", ".dng", ".nef"}
MEDIA_EXTENSIONS = PREVIEWABLE_EXTENSIONS | RAW_EXTENSIONS
SIDECAR_EXTENSIONS = {".xmp", ".aae", ".json", ".thm"}

EXIFTOOL_BATCH_SIZE = 256
EXIFTOOL_TIMEOUT_SECONDS = 120
PLACE_CLUSTER_RADIUS_KM = 0.4
SEQUENCE_MAX_GAP_HOURS = 4
SEQUENCE_MAX_DISTANCE_KM = 100
CACHE_SCHEMA_VERSION = 1
MODEL_SCHEMA_VERSION = 1
