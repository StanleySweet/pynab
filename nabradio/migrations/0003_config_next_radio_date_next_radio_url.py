from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("nabradio", "0002_config_json_data_base"),
    ]

    operations = [
        migrations.AddField(
            model_name="config",
            name="next_radio_date",
            field=models.DateTimeField(default=None, null=True),
        ),
        migrations.AddField(
            model_name="config",
            name="next_radio_url",
            field=models.TextField(default="", null=True),
        ),
    ]
