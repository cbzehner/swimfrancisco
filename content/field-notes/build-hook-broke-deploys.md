+++
draft = true
title = "The build hook that broke deploys"
description = "A relative path worked locally and failed inside Cloudflare Workers Builds."
date = 2026-05-16
weight = 130

[extra]
kind = "lap_note"
lane = "build"
lane_number = 2
lane_label = "Build"
topic = "LAP NOTE"
commit_sha = "bbfb982"
history = "bbfb982"
+++

The generated Worker spot file used to come from a Wrangler build
hook.

Locally, the hook ran from the expected directory. In Cloudflare
Workers Builds, it ran from a different working directory. The
relative path pointed outside the cloned repo, and production deploys
failed.

The fix was not a smarter path trick. The generated file became a
committed artifact. Local commands regenerate it before typecheck,
and a parity test catches drift.

Generated code is fine. Hidden deploy-time generation is where the
project got cut.
