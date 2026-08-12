"""The Ctx object, built once in the root callback and injected into every command.

Carries resolved settings, the API client, output and logging. Commands never
import global state, which is what makes them testable. Everything expensive is a
cached_property so `elva --version` pays for none of it."""
