from django.db import models
import logging

logger = logging.getLogger('django')
#----------------------------CLASSLEVEL-------------------------------

class ClassLevel(models.Model):
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(unique=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.name


#----------------------------SUBJECT-------------------------------

class Subject(models.Model):
    name = models.CharField(max_length=100)
    class_levels = models.ManyToManyField(ClassLevel, related_name='subjects')

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
        ordering = ['name']

    def __str__(self):
        return f"{self.name}_{self.class_levels.name}"
    


#----------------------------THEOREME-------------------------------

class Theorem(models.Model):
    name = models.CharField(max_length=100)
    chapters = models.ManyToManyField(Chapter, related_name='theorems')
    class_levels = models.ManyToManyField(ClassLevel, related_name='theorems')
    subject = models.ForeignKey(Subject, related_name='theorems', on_delete= models.PROTECT, null= True)
    subfield = models.ForeignKey(Subfield,related_name='theorems', on_delete=models.PROTECT, null= True)

    def __str__(self):
        return self.name
    
    


