# Generated manually
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("nabd", "0002_alter_config_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="config",
            name="bottom_led_color",
            field=models.CharField(default="#00FFFF", max_length=7),
        ),
    ]
