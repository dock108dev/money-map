# Money Map UI design

Use the [design requirements](ui-design-requirements.md) and `web/src/styles/glass.css` when changing the interface.

## Layout and behavior

The app shell, sidebar, forms and planning screens use a cool palette and system typography. Preserve print styles.

Cash Flow and goals use plain labels. Life Lab separates assumptions from calculated results. Housing Move puts actions and results before its long form, keeps unknowns, reserves and funding needs visible, and reveals detailed comparisons on demand.

UI changes must preserve financial calculations, source meaning and saved data. Screen-specific styles complement `web/src/styles.css`.

## Visual checks

Check the affected screens at supported sizes, including keyboard focus, long content, disabled actions and error recovery. Existing review records are in [UI verification](ui-verification.md).
