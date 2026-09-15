/**
 * Stub for Next's `server-only` marker.
 *
 * The real package exists so that importing a server module from a Client
 * Component is a build error. It has no runtime behaviour at all, and it only
 * resolves inside Next's bundler — so under Vitest it is aliased to this empty
 * module (see `vitest.config.mts`) and the modules it guards can be tested
 * directly.
 */
export {}
