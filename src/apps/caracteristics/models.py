from django.db import models
import logging

logger = logging.getLogger('django')
#----------------------------CLASSLEVEL-------------------------------

class ClassLevel(models.Model):
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(unique=True)

    class Meta:
        app_label = 'caracteristics'
        ordering = ['order']

    def __str__(self):
        return self.name


#----------------------------SUBJECT-------------------------------

class Subject(models.Model):
    name = models.CharField(max_length=100)
    class_levels = models.ManyToManyField(ClassLevel, related_name='subjects')

    class Meta:
        app_label = 'caracteristics'
        ordering = ['name']

    def __str__(self):
        return self.name
    
    
#----------------------------SUBFIELD-------------------------------

class Subfield(models.Model):
    name = models.CharField(max_length=100)
    class_levels = models.ManyToManyField(ClassLevel, related_name='subfields')
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='subfields')

    def __str__(self):
        return self.name



#----------------------------CHAPTER-------------------------------
class Chapter(models.Model):
    name = models.CharField(max_length=100)
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='chapters', null = True)
    class_levels = models.ManyToManyField(ClassLevel, related_name = 'chapters')
    subfield = models.ForeignKey(Subfield, on_delete=models.PROTECT, related_name='chapters', null = True)

    class Meta:
        app_label = 'caracteristics'
        ordering = ['name']

    def __str__(self):
        return f"{self.name}_{self.class_levels_display}"
    
    @property
    def class_levels_display(self):
        """Display all class levels as a comma-separated string"""
        return ", ".join([cl.name for cl in self.class_levels.all()])


#----------------------------THEOREME-------------------------------

class Theorem(models.Model):
    name = models.CharField(max_length=100)
    chapters = models.ManyToManyField(Chapter, related_name='theorems')
    class_levels = models.ManyToManyField(ClassLevel, related_name='theorems')
    subject = models.ForeignKey(Subject, related_name='theorems', on_delete= models.PROTECT, null= True)
    subfield = models.ForeignKey(Subfield,related_name='theorems', on_delete=models.PROTECT, null= True)

    def __str__(self):
        return self.name
    
    


#----------------------------SCHOOL-------------------------------

def school_search_key(*parts):
    """Texte de recherche : minuscules, sans accents ni ponctuation (arabe conservé)."""
    import re
    import unicodedata
    s = unicodedata.normalize('NFKD', ' '.join(p for p in parts if p))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r'[^\w؀-ۿ]+', ' ', s).strip()


class School(models.Model):
    """Établissement scolaire marocain (listes officielles du ministère, data.gov.ma)."""
    KIND_CHOICES = [
        ('lycee', 'Lycée public'),
        ('college', 'Collège public'),
        ('cpge', 'CPGE'),
        ('prive', 'Établissement privé'),
    ]

    name = models.CharField(max_length=255)
    name_ar = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    region = models.CharField(max_length=120, blank=True)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    search = models.CharField(max_length=700, editable=False)

    class Meta:
        app_label = 'caracteristics'
        ordering = ['name']

    def save(self, *args, **kwargs):
        self.search = school_search_key(self.name, self.name_ar, self.city)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.city})" if self.city else self.name
