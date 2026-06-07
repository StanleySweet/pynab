# Generated manually
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("nabttsd", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="config",
            name="length_scale",
            field=models.FloatField(default=1.5),
        ),
    ]
