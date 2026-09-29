from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('caracteristics', '0002_school'),
        ('users', '0007_userprofile_email_verified'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='school',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='members', to='caracteristics.school'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='school_name',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
