EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sessions", "closures", "effective_start", "schedule_basis"],
    "properties": {
        "sessions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["day", "type", "start", "end", "evidence"],
                "properties": {
                    "day": {
                        "type": "string",
                        "enum": [
                            "monday",
                            "tuesday",
                            "wednesday",
                            "thursday",
                            "friday",
                            "saturday",
                            "sunday",
                        ],
                    },
                    "type": {
                        "type": "string",
                        "enum": [
                            "lap_swim",
                            "family_swim",
                            "senior_swim",
                        ],
                    },
                    "start": {
                        "type": "string",
                        "pattern": r"^([01]\d|2[0-3]):[0-5]\d$",
                    },
                    "end": {
                        "type": "string",
                        "pattern": r"^([01]\d|2[0-3]):[0-5]\d$",
                    },
                    "evidence": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "pool": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "notes": {
                        "type": "string",
                        "minLength": 1,
                    },
                },
            },
        },
        "schedule_basis": {
            "type": "string",
            "enum": [
                "swim_schedule",
                "pool_hours",
                "facility_hours",
                "amenity_only",
                "temporarily_closed",
                "unknown",
            ],
        },
        "closures": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["start", "end", "reason"],
                "properties": {
                    "start": {
                        "type": "string",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    },
                    "end": {
                        "type": "string",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    },
                    "reason": {"type": "string", "minLength": 1},
                    "start_time": {
                        "type": "string",
                        "pattern": r"^([01]\d|2[0-3]):[0-5]\d$",
                    },
                    "end_time": {
                        "type": "string",
                        "pattern": r"^([01]\d|2[0-3]):[0-5]\d$",
                    },
                },
            },
        },
        "access_hours": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["day", "start", "end", "label", "evidence"],
                "properties": {
                    "day": {
                        "type": "string",
                        "enum": [
                            "monday",
                            "tuesday",
                            "wednesday",
                            "thursday",
                            "friday",
                            "saturday",
                            "sunday",
                        ],
                    },
                    "start": {
                        "type": "string",
                        "pattern": r"^([01]\d|2[0-3]):[0-5]\d$",
                    },
                    "end": {
                        "type": "string",
                        "pattern": r"^([01]\d|2[0-3]):[0-5]\d$",
                    },
                    "label": {"type": "string", "minLength": 1},
                    "evidence": {"type": "string", "minLength": 1},
                    "notes": {"type": "string", "minLength": 1},
                },
            },
        },
        "access_exceptions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["date", "start", "end", "label", "reason", "evidence"],
                "properties": {
                    "date": {
                        "type": "string",
                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    },
                    "start": {
                        "type": "string",
                        "pattern": r"^([01]\d|2[0-3]):[0-5]\d$",
                    },
                    "end": {
                        "type": "string",
                        "pattern": r"^([01]\d|2[0-3]):[0-5]\d$",
                    },
                    "label": {"type": "string", "minLength": 1},
                    "reason": {"type": "string", "minLength": 1},
                    "evidence": {"type": "string", "minLength": 1},
                    "notes": {"type": "string", "minLength": 1},
                },
            },
        },
        "effective_start": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
        },
        "effective_end": {
            "anyOf": [
                {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                {"type": "null"},
            ]
        },
    },
}
