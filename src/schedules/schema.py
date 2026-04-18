EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sessions", "closures", "schedule_effective"],
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
                            "lessons",
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
                },
            },
        },
        "schedule_effective": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
        },
        "schedule_effective_end": {
            "anyOf": [
                {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                {"type": "null"},
            ]
        },
    },
}

