import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';

const projectRoot = path.resolve(import.meta.dirname, '..');
const sourceRoot = path.join(projectRoot, 'src');
const localesRoot = path.join(sourceRoot, 'i18n', 'locales');
const errors = [];

function flattenResource(value, prefix = '', result = new Map()) {
  for (const [key, childValue] of Object.entries(value)) {
    const childKey = prefix ? `${prefix}.${key}` : key;
    if (typeof childValue === 'string') result.set(childKey, childValue);
    else if (childValue && typeof childValue === 'object' && !Array.isArray(childValue)) {
      flattenResource(childValue, childKey, result);
    } else {
      errors.push(`Translation value must be a string or object: ${childKey}`);
    }
  }
  return result;
}

const localeResources = new Map();
const localeDirectories = fs.readdirSync(localesRoot, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name)
  .sort();

for (const locale of localeDirectories) {
  const namespaceResources = new Map();
  for (const fileName of fs.readdirSync(path.join(localesRoot, locale)).filter((name) => name.endsWith('.json')).sort()) {
    const namespace = path.basename(fileName, '.json');
    const resourcePath = path.join(localesRoot, locale, fileName);
    try {
      const resourceText = fs.readFileSync(resourcePath, 'utf8');
      const jsonSource = ts.parseJsonText(resourcePath, resourceText);
      function findDuplicateJsonKeys(node) {
        if (ts.isObjectLiteralExpression(node)) {
          const keys = new Set();
          for (const property of node.properties) {
            if (!ts.isPropertyAssignment(property)) continue;
            const key = property.name.getText(jsonSource).replace(/^['"]|['"]$/g, '');
            if (keys.has(key)) {
              const position = jsonSource.getLineAndCharacterOfPosition(property.name.getStart(jsonSource));
              errors.push(`${path.relative(projectRoot, resourcePath)}:${position.line + 1} has duplicate key '${key}'.`);
            }
            keys.add(key);
          }
        }
        ts.forEachChild(node, findDuplicateJsonKeys);
      }
      findDuplicateJsonKeys(jsonSource);
      namespaceResources.set(namespace, flattenResource(JSON.parse(resourceText)));
    } catch (error) {
      errors.push(`${path.relative(projectRoot, resourcePath)} is not valid JSON: ${error.message}`);
    }
  }
  localeResources.set(locale, namespaceResources);
}

const englishNamespaces = localeResources.get('en');
if (!englishNamespaces) errors.push('The required English locale is missing.');

function interpolationNames(value) {
  return [...value.matchAll(/{{\s*([A-Za-z0-9_]+)(?:\s*,[^}]*)?\s*}}/g)]
    .map((match) => match[1])
    .sort();
}

function richTextPlaceholders(value) {
  return [...value.matchAll(/<\/?([A-Za-z][A-Za-z0-9]*|[0-9]+)(?:\s[^>]*)?>/g)]
    .map((match) => match[1])
    .sort();
}

if (englishNamespaces) {
  for (const [locale, namespaces] of localeResources) {
    if (locale === 'en') continue;
    const englishNamespaceNames = [...englishNamespaces.keys()].sort();
    const localeNamespaceNames = [...namespaces.keys()].sort();
    if (englishNamespaceNames.join('|') !== localeNamespaceNames.join('|')) {
      errors.push(`${locale} namespaces do not match English.`);
      continue;
    }
    for (const namespace of englishNamespaceNames) {
      const englishResource = englishNamespaces.get(namespace);
      const localeResource = namespaces.get(namespace);
      const englishKeys = [...englishResource.keys()].sort();
      const localeKeys = [...localeResource.keys()].sort();
      if (englishKeys.join('|') !== localeKeys.join('|')) {
        errors.push(`${locale}:${namespace} keys do not match English.`);
        continue;
      }
      for (const key of englishKeys) {
        const englishVariables = interpolationNames(englishResource.get(key));
        const localeVariables = interpolationNames(localeResource.get(key));
        if (englishVariables.join('|') !== localeVariables.join('|')) {
          errors.push(`${locale}:${namespace}:${key} interpolation variables do not match English.`);
        }
        const englishRichText = richTextPlaceholders(englishResource.get(key));
        const localeRichText = richTextPlaceholders(localeResource.get(key));
        if (englishRichText.join('|') !== localeRichText.join('|')) {
          errors.push(`${locale}:${namespace}:${key} rich-text placeholders do not match English.`);
        }
      }
    }
  }

  for (const [namespace, resource] of englishNamespaces) {
    const pluralGroups = new Map();
    for (const key of resource.keys()) {
      const pluralMatch = key.match(/^(.*)_(zero|one|two|few|many|other)$/);
      if (!pluralMatch) continue;
      const forms = pluralGroups.get(pluralMatch[1]) ?? new Set();
      forms.add(pluralMatch[2]);
      pluralGroups.set(pluralMatch[1], forms);
    }
    for (const [baseKey, forms] of pluralGroups) {
      if (!forms.has('other')) errors.push(`${namespace}:${baseKey} plural group is missing _other.`);
    }
  }
}

const sourceFiles = [];
function visitDirectory(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== 'i18n' && entry.name !== 'test') visitDirectory(fullPath);
    } else if (/\.(ts|tsx)$/.test(entry.name) && !entry.name.endsWith('.d.ts')) {
      sourceFiles.push(fullPath);
    }
  }
}
visitDirectory(sourceRoot);

const userCopyAttributes = new Set([
  'aria-label', 'title', 'placeholder', 'alt', 'label', 'description',
  'emptyMessage', 'helperText', 'confirmText', 'loadingText',
]);
const visibleObjectProperties = new Set([
  'title', 'label', 'description', 'desc', 'placeholder', 'emptyMessage',
  'helperText', 'confirmText', 'loadingText',
]);
const userMessageSetters = /^set[A-Za-z]*(?:Error|Success|Message|Warning|Notice)$/;

function isIgnored(sourceText, nodeStart) {
  const before = sourceText.slice(Math.max(0, nodeStart - 240), nodeStart);
  const lastLine = before.split(/\r?\n/).slice(-2).join('\n');
  return /i18n-ignore:\s*\S+/.test(lastLine);
}

function looksUserFacing(value) {
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (!/[A-Za-z]{2}/.test(normalized)) return false;
  if (/^(OpenAQ|PurpleAir|AirGradient|Geoapify|COMPASS|NRDC|UTC|AQI)$/.test(normalized)) return false;
  if (/^(https?:|\/|[\w.-]+\.(com|org|svg|png|csv|json))/.test(normalized)) return false;
  if (/^[a-z0-9_.:/-]+$/.test(normalized) && !normalized.includes(' ')) return false;
  return true;
}

function templateStaticText(node) {
  if (ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
  if (!ts.isTemplateExpression(node)) return '';
  return [node.head.text, ...node.templateSpans.map((span) => span.literal.text)].join(' ');
}

function expressionFromJsxAttribute(node) {
  if (!node.initializer) return null;
  if (ts.isStringLiteral(node.initializer)) return node.initializer;
  if (ts.isJsxExpression(node.initializer)) return node.initializer.expression ?? null;
  return null;
}

function keyExists(fullKey) {
  if (!englishNamespaces) return false;
  const colonIndex = fullKey.indexOf(':');
  if (colonIndex >= 0) {
    const namespace = fullKey.slice(0, colonIndex);
    const key = fullKey.slice(colonIndex + 1);
    const resource = englishNamespaces.get(namespace);
    return resource?.has(key) || resource?.has(`${key}_other`) || false;
  }
  if (englishNamespaces.get('common')?.has(fullKey)
      || englishNamespaces.get('common')?.has(`${fullKey}_other`)) return true;
  return [...englishNamespaces.values()].some(
    (resource) => resource.has(fullKey) || resource.has(`${fullKey}_other`),
  );
}

function report(filePath, sourceFile, node, message) {
  if (isIgnored(sourceFile.text, node.getStart(sourceFile))) return;
  const position = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
  errors.push(`${path.relative(projectRoot, filePath)}:${position.line + 1}:${position.character + 1} ${message}`);
}

for (const filePath of sourceFiles) {
  const sourceText = fs.readFileSync(filePath, 'utf8');
  const sourceFile = ts.createSourceFile(
    filePath,
    sourceText,
    ts.ScriptTarget.Latest,
    true,
    filePath.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );

  function inspectTranslationKey(keyNode) {
    if (!keyExists(keyNode.text)) report(filePath, sourceFile, keyNode, `missing translation key '${keyNode.text}'.`);
  }

  function visit(node) {
    if (ts.isJsxText(node) && looksUserFacing(node.text)) {
      report(filePath, sourceFile, node, `hardcoded JSX text '${node.text.replace(/\s+/g, ' ').trim()}'.`);
    }

    if (ts.isJsxAttribute(node)) {
      const attributeName = node.name.getText(sourceFile);
      if (attributeName === 'i18nKey' && node.initializer && ts.isStringLiteral(node.initializer)) {
        let fullKey = node.initializer.text;
        const parentAttributes = node.parent?.properties ?? [];
        const namespaceAttribute = parentAttributes.find((attribute) => (
          ts.isJsxAttribute(attribute) && attribute.name.getText(sourceFile) === 'ns'
        ));
        if (namespaceAttribute?.initializer && ts.isStringLiteral(namespaceAttribute.initializer)) {
          fullKey = `${namespaceAttribute.initializer.text}:${fullKey}`;
        }
        if (!keyExists(fullKey)) report(filePath, sourceFile, node.initializer, `missing translation key '${fullKey}'.`);
      }
      const attributeExpression = expressionFromJsxAttribute(node);
      if (userCopyAttributes.has(attributeName)
          && attributeExpression
          && (ts.isStringLiteral(attributeExpression)
            || ts.isNoSubstitutionTemplateLiteral(attributeExpression)
            || ts.isTemplateExpression(attributeExpression))) {
        const staticText = ts.isStringLiteral(attributeExpression)
          ? attributeExpression.text
          : templateStaticText(attributeExpression);
        if (looksUserFacing(staticText)) {
          report(filePath, sourceFile, attributeExpression, `hardcoded ${attributeName} text '${staticText.replace(/\s+/g, ' ').trim()}'.`);
        }
      }
    }

    if (ts.isJsxExpression(node)
        && !ts.isJsxAttribute(node.parent)
        && node.expression
        && (ts.isNoSubstitutionTemplateLiteral(node.expression) || ts.isTemplateExpression(node.expression))) {
      const staticText = templateStaticText(node.expression);
      if (looksUserFacing(staticText)) {
        report(filePath, sourceFile, node.expression, `hardcoded JSX template text '${staticText.replace(/\s+/g, ' ').trim()}'.`);
      }
    }

    if (ts.isCallExpression(node)) {
      const expressionText = node.expression.getText(sourceFile);
      const firstArgument = node.arguments[0];
      if ((expressionText === 't' || expressionText.endsWith('.t'))
          && firstArgument
          && ts.isStringLiteral(firstArgument)) {
        inspectTranslationKey(firstArgument);
      }
      if ((expressionText === 'alert' || expressionText === 'confirm'
          || expressionText.endsWith('.alert') || expressionText.endsWith('.confirm'))
          && firstArgument
          && (ts.isStringLiteral(firstArgument) || ts.isNoSubstitutionTemplateLiteral(firstArgument) || ts.isTemplateExpression(firstArgument))
          && looksUserFacing(ts.isTemplateExpression(firstArgument) ? templateStaticText(firstArgument) : firstArgument.text)) {
        report(filePath, sourceFile, firstArgument, `hardcoded ${expressionText} text '${ts.isTemplateExpression(firstArgument) ? templateStaticText(firstArgument) : firstArgument.text}'.`);
      }
      if (userMessageSetters.test(expressionText)
          && firstArgument
          && (ts.isStringLiteral(firstArgument) || ts.isNoSubstitutionTemplateLiteral(firstArgument) || ts.isTemplateExpression(firstArgument))
          && looksUserFacing(ts.isTemplateExpression(firstArgument) ? templateStaticText(firstArgument) : firstArgument.text)) {
        report(filePath, sourceFile, firstArgument, `hardcoded user message '${ts.isTemplateExpression(firstArgument) ? templateStaticText(firstArgument) : firstArgument.text}'.`);
      }
    }

    if (ts.isPropertyAssignment(node)
        && visibleObjectProperties.has(node.name.getText(sourceFile).replace(/["']/g, ''))
        && (ts.isStringLiteral(node.initializer) || ts.isNoSubstitutionTemplateLiteral(node.initializer) || ts.isTemplateExpression(node.initializer))
        && looksUserFacing(ts.isTemplateExpression(node.initializer) ? templateStaticText(node.initializer) : node.initializer.text)) {
      report(filePath, sourceFile, node.initializer, `hardcoded visible property '${ts.isTemplateExpression(node.initializer) ? templateStaticText(node.initializer) : node.initializer.text}'.`);
    }

    if (ts.isBinaryExpression(node)
        && /(?:^|\.)title$/.test(node.left.getText(sourceFile))
        && (ts.isStringLiteral(node.right) || ts.isNoSubstitutionTemplateLiteral(node.right) || ts.isTemplateExpression(node.right))) {
      report(filePath, sourceFile, node.right, `hardcoded title '${ts.isTemplateExpression(node.right) ? templateStaticText(node.right) : node.right.text}'.`);
    }

    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
}

if (errors.length > 0) {
  console.error(`i18n validation failed with ${errors.length} issue(s):`);
  for (const error of errors) console.error(`- ${error}`);
  process.exit(1);
}

const localeCounts = [...localeResources.entries()].map(([locale, localeNamespaces]) => {
  const keyCount = [...localeNamespaces.values()].reduce((count, resource) => count + resource.size, 0);
  return `${locale}: ${localeNamespaces.size} namespaces / ${keyCount} keys`;
});
console.log(`i18n validation passed: ${localeCounts.join('; ')}.`);
