export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  options?: { className?: string; text?: string },
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (options?.className) node.className = options.className;
  if (options?.text !== undefined) node.textContent = options.text;
  return node;
}
