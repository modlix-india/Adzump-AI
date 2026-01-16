# Model Files Directory

Place your pickle files in this directory:

- `lgbm_models.pkl` - Trained LightGBM models dictionary
- `uncertainty_sigmas.pkl` - Uncertainty sigma values for each model
- `reference_columns.pkl` - Reference columns for feature alignment

## How to generate these files

Run this code after training your models:

```python
import pickle
import os

model_dir = 'mlops/models'
os.makedirs(model_dir, exist_ok=True)

# Save models dictionary
with open(os.path.join(model_dir, 'lgbm_models.pkl'), 'wb') as f:
    pickle.dump(models, f)

# Save uncertainty sigmas
with open(os.path.join(model_dir, 'uncertainty_sigmas.pkl'), 'wb') as f:
    pickle.dump(uncertainty_sigmas, f)

# Save reference columns
reference_columns = {
    'weekly_columns': X_train_weekly_processed.columns.tolist(),
    'monthly_columns': X_train_monthly_processed.columns.tolist()
}
with open(os.path.join(model_dir, 'reference_columns.pkl'), 'wb') as f:
    pickle.dump(reference_columns, f)
```
