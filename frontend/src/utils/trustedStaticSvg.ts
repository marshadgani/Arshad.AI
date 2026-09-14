/**
 * Nominal type for markup safe to pass to `dangerouslySetInnerHTML`. Only
 * {@link trustedStaticSvg} produces it, so a plain `string` — which may carry
 * interpolated user input — can never be assigned to a constant declared
 * with this type.
 */
export type TrustedStaticSvg = string & { readonly __brand: 'TrustedStaticSvg' };

/**
 * Tagged template that turns "must stay a literal with no interpolation" from
 * a comment into a compile-time check: `TemplateStringsArray` is the only
 * parameter, so any `${...}` in the literal is an excess argument and fails
 * to typecheck.
 */
export function trustedStaticSvg(strings: TemplateStringsArray): TrustedStaticSvg {
  return strings.raw.join('') as TrustedStaticSvg;
}
