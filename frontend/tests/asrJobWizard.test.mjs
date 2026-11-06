import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { FormStore } = require('../node_modules/rc-field-form/lib/useForm');

function mountedWizardForm() {
  const store = new FormStore(() => {});
  const form = store.getForm();
  const hooks = form.getInternalHooks('RC_FORM_INTERNAL_HOOKS');
  for (const name of ['audio_ids', 'test_model_slot', 'reference_a_model_slot', 'reference_b_model_slot', 'mode']) {
    const required = name !== 'mode';
    hooks.registerField({ getNamePath: () => [name], props: { rules: required ? [{ required: true }] : [] },
      validateRules: () => {
        const value = form.getFieldValue(name);
        const missing = value === undefined || value === null || value === '' || (Array.isArray(value) && value.length === 0);
        return required && missing ? Promise.reject([{ rule: {}, errors: [`${name} required`] }]) : Promise.resolve();
      },
      onStoreChange() {}, isFieldTouched: () => false, isFieldDirty: () => false,
      getErrors: () => [], getWarnings: () => [], isListField: () => false });
  }
  return form;
}

test('three-step job submit validates every step and returns audio plus all model slots', async () => {
  const form = mountedWizardForm();
  form.setFieldsValue({ audio_ids: [11], test_model_slot: '1:2:3',
    reference_a_model_slot: '4:5:6', reference_b_model_slot: '7:8:9', mode: 'NOW' });
  const submitted = await form.validateFields();
  assert.deepEqual(submitted.audio_ids, [11]);
  assert.equal(submitted.test_model_slot, '1:2:3');
  assert.equal(submitted.reference_a_model_slot, '4:5:6');
  assert.equal(submitted.reference_b_model_slot, '7:8:9');
});

test('final wizard validation rejects a missing field from an earlier step', async () => {
  const form = mountedWizardForm();
  form.setFieldsValue({ audio_ids: [11], test_model_slot: '1:2:3', mode: 'NOW' });
  await assert.rejects(form.validateFields());
});
